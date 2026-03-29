from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import require_active_user
from app.media import service
from app.media.dependencies import require_media_uploader
from app.media.models import Media
from app.media.schemas import MediaStatusResponse, UploadUrlRequest, UploadUrlResponse
from app.media.storage import StorageClient, get_storage
from app.users.models import User

router = APIRouter(tags=["media"])


@router.post("/media/upload-url", response_model=UploadUrlResponse)
async def request_upload_url(
    data: UploadUrlRequest,
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UploadUrlResponse:
    return await service.request_upload_url(data, user, storage)


@router.post("/media/{media_id}/confirm", response_model=MediaStatusResponse)
async def confirm_upload(
    media: Annotated[Media, Depends(require_media_uploader)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> MediaStatusResponse:
    updated = await service.confirm_upload(media, storage)
    return MediaStatusResponse(
        id=updated.id,
        status=updated.status,
        kind=updated.kind,
        context=updated.context,
        original_filename=updated.original_filename,
        variants=updated.variants,
    )
