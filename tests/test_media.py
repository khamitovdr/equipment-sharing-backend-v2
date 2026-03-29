from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.enums import MediaContext, MediaKind, MediaStatus
from app.media.models import Media
from app.media.storage import StorageClient
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


@pytest.fixture
async def storage() -> StorageClient:
    from app.core.config import get_settings

    settings = get_settings()
    client = StorageClient(
        endpoint_url=settings.storage.endpoint_url,
        access_key=settings.storage.access_key,
        secret_key=settings.storage.secret_key,
        bucket=settings.storage.bucket,
    )
    await client.ensure_bucket()
    return client


async def test_storage_upload_and_download(storage: StorageClient) -> None:
    key = "test/hello.txt"
    await storage.upload(key, b"hello world", "text/plain")

    assert await storage.exists(key)

    data = await storage.download(key)
    assert data == b"hello world"

    await storage.delete(key)
    assert not await storage.exists(key)


async def test_storage_presigned_upload_url(storage: StorageClient) -> None:
    url = await storage.generate_upload_url("test/upload.txt", "text/plain", expires=60)
    assert "test/upload.txt" in url
    assert "X-Amz-Signature" in url


async def test_storage_presigned_download_url(storage: StorageClient) -> None:
    key = "test/download.txt"
    await storage.upload(key, b"download me", "text/plain")

    url = await storage.generate_download_url(key, expires=60)
    assert "test/download.txt" in url
    assert "X-Amz-Signature" in url

    await storage.delete(key)


async def test_storage_delete_prefix(storage: StorageClient) -> None:
    await storage.upload("test/prefix/a.txt", b"a", "text/plain")
    await storage.upload("test/prefix/b.txt", b"b", "text/plain")
    await storage.upload("test/other/c.txt", b"c", "text/plain")

    await storage.delete_prefix("test/prefix/")

    assert not await storage.exists("test/prefix/a.txt")
    assert not await storage.exists("test/prefix/b.txt")
    assert await storage.exists("test/other/c.txt")

    await storage.delete("test/other/c.txt")


async def test_request_upload_url(client: AsyncClient, create_user: Any, mock_storage: AsyncMock) -> None:  # noqa: ARG001
    _, token = await create_user()
    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "avatar.jpg",
            "content_type": "image/jpeg",
            "file_size": 1_000_000,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "media_id" in data
    assert "upload_url" in data
    assert "expires_in" in data


async def test_upload_url_rejects_invalid_content_type(
    client: AsyncClient,
    create_user: Any,
    mock_storage: AsyncMock,  # noqa: ARG001
) -> None:
    _, token = await create_user()
    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "malware.exe",
            "content_type": "application/x-msdownload",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


async def test_upload_url_rejects_oversized_file(
    client: AsyncClient,
    create_user: Any,
    mock_storage: AsyncMock,  # noqa: ARG001
) -> None:
    _, token = await create_user()
    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "huge.jpg",
            "content_type": "image/jpeg",
            "file_size": 100_000_000,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


async def test_upload_url_requires_auth(client: AsyncClient, mock_storage: AsyncMock) -> None:  # noqa: ARG001
    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "avatar.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
    )
    assert resp.status_code == 401


async def test_confirm_upload(client: AsyncClient, create_user: Any, mock_storage: AsyncMock) -> None:  # noqa: ARG001
    _, token = await create_user()

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "document",
            "context": "listing",
            "filename": "spec.pdf",
            "content_type": "application/pdf",
            "file_size": 5000,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    media_id = resp.json()["media_id"]

    confirm_resp = await client.post(
        f"/media/{media_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert confirm_resp.status_code == 200
    data = confirm_resp.json()
    assert data["status"] == "processing"


async def test_confirm_rejects_non_uploader(client: AsyncClient, create_user: Any, mock_storage: AsyncMock) -> None:  # noqa: ARG001
    _, token1 = await create_user(email="uploader@example.com")
    _, token2 = await create_user(email="other@example.com", phone="+79001112233")

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token1}"},
    )
    media_id = resp.json()["media_id"]

    confirm_resp = await client.post(
        f"/media/{media_id}/confirm",
        headers={"Authorization": f"Bearer {token2}"},
    )

    assert confirm_resp.status_code == 403


async def test_get_media_status(client: AsyncClient, create_user: Any, mock_storage: AsyncMock) -> None:  # noqa: ARG001
    _, token = await create_user()

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    media_id = resp.json()["media_id"]

    status_resp = await client.get(
        f"/media/{media_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "pending_upload"


async def test_delete_media(client: AsyncClient, create_user: Any, mock_storage: AsyncMock) -> None:  # noqa: ARG001
    _, token = await create_user()

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    media_id = resp.json()["media_id"]

    del_resp = await client.delete(
        f"/media/{media_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 204

    status_resp = await client.get(
        f"/media/{media_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_resp.status_code == 404


async def test_retry_failed_media(client: AsyncClient, create_user: Any, mock_storage: AsyncMock) -> None:  # noqa: ARG001
    _, token = await create_user()

    resp = await client.post(
        "/media/upload-url",
        json={
            "kind": "photo",
            "context": "user_profile",
            "filename": "photo.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    media_id = resp.json()["media_id"]

    from uuid import UUID

    from app.core.enums import MediaStatus
    from app.media.models import Media as MediaModel

    await MediaModel.filter(id=UUID(media_id)).update(status=MediaStatus.FAILED)

    retry_resp = await client.post(
        f"/media/{media_id}/retry",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert retry_resp.status_code == 200
    assert retry_resp.json()["status"] == "processing"
