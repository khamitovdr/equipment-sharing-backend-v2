from uuid import UUID, uuid4

from app.core.config import get_settings
from app.core.enums import MediaKind, MediaOwnerType, MediaStatus
from app.core.exceptions import AppValidationError, NotFoundError, PermissionDeniedError
from app.media.models import Media
from app.media.schemas import ProfilePhotoRead, UploadUrlRequest, UploadUrlResponse
from app.media.storage import StorageClient
from app.observability.tracing import traced
from app.users.models import User


def _max_size_bytes(kind: MediaKind) -> int:
    settings = get_settings()
    mb = {
        MediaKind.PHOTO: settings.media.max_photo_size_mb,
        MediaKind.VIDEO: settings.media.max_video_size_mb,
        MediaKind.DOCUMENT: settings.media.max_document_size_mb,
    }[kind]
    return mb * 1024 * 1024


def _allowed_types(kind: MediaKind) -> list[str]:
    settings = get_settings()
    return {
        MediaKind.PHOTO: settings.media.allowed_photo_types,
        MediaKind.VIDEO: settings.media.allowed_video_types,
        MediaKind.DOCUMENT: settings.media.allowed_document_types,
    }[kind]


@traced
async def request_upload_url(
    data: UploadUrlRequest,
    user: User,
    storage: StorageClient,
) -> UploadUrlResponse:
    if data.content_type not in _allowed_types(data.kind):
        raise AppValidationError(f"Content type '{data.content_type}' is not allowed for {data.kind.value}")

    max_size = _max_size_bytes(data.kind)
    if data.file_size > max_size:
        raise AppValidationError(f"File size exceeds maximum of {max_size // (1024 * 1024)} MB for {data.kind.value}")

    media_id = uuid4()
    upload_key = f"pending/{media_id}/{data.filename}"

    await Media.create(
        id=media_id,
        uploaded_by=user,
        kind=data.kind,
        context=data.context,
        status=MediaStatus.PENDING_UPLOAD,
        original_filename=data.filename,
        content_type=data.content_type,
        file_size=data.file_size,
        upload_key=upload_key,
    )

    settings = get_settings()
    expires = settings.storage.presigned_url_expiry_seconds
    upload_url = await storage.generate_upload_url(upload_key, data.content_type, expires)

    return UploadUrlResponse(
        media_id=media_id,
        upload_url=upload_url,
        expires_in=expires,
    )


@traced
async def confirm_upload(
    media: Media,
    storage: StorageClient,
) -> Media:
    if media.status != MediaStatus.PENDING_UPLOAD:
        raise AppValidationError(f"Media is in '{media.status}' state, expected 'pending_upload'")

    if not await storage.exists(media.upload_key):
        raise NotFoundError("Uploaded file not found in storage")

    media.status = MediaStatus.PROCESSING
    await media.save()

    from app.media.worker import get_arq_pool

    pool = await get_arq_pool()
    await pool.enqueue_job("process_media_job", str(media.id))

    return media


@traced
async def delete_media(media: Media, storage: StorageClient) -> None:
    await storage.delete_prefix(f"pending/{media.id}/")
    await storage.delete_prefix(f"media/{media.id}/")
    await media.delete()


@traced
async def retry_media(media: Media) -> Media:
    if media.status != MediaStatus.FAILED:
        raise AppValidationError("Only failed media can be retried")
    media.status = MediaStatus.PROCESSING
    await media.save()

    from app.media.worker import get_arq_pool

    pool = await get_arq_pool()
    await pool.enqueue_job("process_media_job", str(media.id))

    return media


@traced
async def get_profile_photo(
    owner_type: MediaOwnerType,
    owner_id: str,
    storage: StorageClient,
) -> ProfilePhotoRead | None:
    """Get profile photo for an entity, generating presigned download URLs."""
    media = await Media.filter(
        owner_type=owner_type,
        owner_id=owner_id,
        kind=MediaKind.PHOTO,
        status=MediaStatus.READY,
    ).first()
    if media is None:
        return None

    settings = get_settings()
    expires = settings.storage.presigned_url_expiry_seconds

    medium_key = media.variants.get("medium", "")
    small_key = media.variants.get("small", "")

    return ProfilePhotoRead(
        id=media.id,
        medium_url=await storage.generate_download_url(medium_key, expires) if medium_key else "",
        small_url=await storage.generate_download_url(small_key, expires) if small_key else "",
    )


@traced
async def attach_profile_photo(
    media_id: UUID | None,
    owner_type: MediaOwnerType,
    owner_id: str,
    user: User,
    storage: StorageClient,
) -> None:
    """Attach a profile photo. Detaches existing photo (becomes orphan for cleanup)."""
    _ = storage  # reserved for future use

    # Detach any existing profile photo
    await Media.filter(
        owner_type=owner_type,
        owner_id=owner_id,
        kind=MediaKind.PHOTO,
    ).update(owner_type=None, owner_id=None)

    if media_id is None:
        return

    media = await Media.get_or_none(id=media_id).prefetch_related("uploaded_by")
    if media is None:
        raise NotFoundError("Media not found")
    if media.status != MediaStatus.READY:
        raise AppValidationError("Media is not ready")

    uploader: User = media.uploaded_by
    if uploader.id != user.id:
        raise PermissionDeniedError("You can only attach your own uploads")
    if media.kind != MediaKind.PHOTO:
        raise AppValidationError("Only photos can be used as profile photo")

    media.owner_type = owner_type
    media.owner_id = owner_id
    await media.save()
