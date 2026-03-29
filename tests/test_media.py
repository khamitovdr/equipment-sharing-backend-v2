from typing import Any
from uuid import uuid4

from app.core.enums import MediaContext, MediaKind, MediaStatus
from app.media.models import Media
from app.users.models import User


async def test_create_media_record(create_user: Any) -> None:
    user_data, _ = await create_user()
    user = await User.get(id=user_data["id"])

    media = await Media.create(
        id=uuid4(),
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.USER_PROFILE,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename="photo.jpg",
        content_type="image/jpeg",
        file_size=1024,
        upload_key=f"pending/{uuid4()}/photo.jpg",
    )

    fetched = await Media.get(id=media.id)
    assert fetched.kind == MediaKind.PHOTO
    assert fetched.context == MediaContext.USER_PROFILE
    assert fetched.status == MediaStatus.PENDING_UPLOAD
    assert fetched.owner_type is None
    assert fetched.owner_id is None
    assert fetched.variants == {}


async def test_media_owner_assignment() -> None:
    from app.core.enums import MediaOwnerType

    user = await User.create(
        id="TSTU01",
        email="media-test@example.com",
        hashed_password="x",
        phone="+79991234567",
        name="Test",
        surname="User",
    )
    media = await Media.create(
        id=uuid4(),
        uploaded_by=user,
        kind=MediaKind.PHOTO,
        context=MediaContext.LISTING,
        original_filename="listing.jpg",
        content_type="image/jpeg",
        file_size=2048,
        upload_key="pending/test/listing.jpg",
    )

    media.owner_type = MediaOwnerType.LISTING
    media.owner_id = "LST001"
    media.status = MediaStatus.READY
    media.variants = {"large": "media/test/large.webp", "medium": "media/test/medium.webp"}
    await media.save()

    fetched = await Media.get(id=media.id)
    assert fetched.owner_type == MediaOwnerType.LISTING
    assert fetched.owner_id == "LST001"
    assert fetched.status == MediaStatus.READY
    assert fetched.variants["large"] == "media/test/large.webp"
