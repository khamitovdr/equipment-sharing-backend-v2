from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import require_active_user, require_platform_admin, require_platform_owner
from app.core.enums import MediaOwnerType
from app.media import service as media_service
from app.media.storage import StorageClient, get_storage
from app.users import service
from app.users.models import User
from app.users.schemas import (
    AdminRoleUpdate,
    LoginRequest,
    PrivilegeUpdate,
    TokenResponse,
    UserCreate,
    UserRead,
    UserUpdate,
)

router = APIRouter()


@router.post("/users/")
async def register(data: UserCreate) -> TokenResponse:
    return await service.register(data)


@router.post("/users/token")
async def login(data: LoginRequest) -> TokenResponse:
    return await service.authenticate(data.email, data.password)


@router.get("/users/me", response_model=UserRead)
async def get_me(
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, user.id, storage)
    user_read = UserRead.model_validate(user)
    user_read.profile_photo = photo
    return user_read


@router.patch("/users/me", response_model=UserRead)
async def update_me(
    data: UserUpdate,
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    updated = await service.update_me(user, data, storage)
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, updated.id, storage)
    user_read = UserRead.model_validate(updated)
    user_read.profile_photo = photo
    return user_read


@router.get("/users/{user_id}", response_model=UserRead)
async def get_user(
    user_id: str,
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    user = await service.get_by_id(user_id)
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, user.id, storage)
    user_read = UserRead.model_validate(user)
    user_read.profile_photo = photo
    return user_read


@router.patch("/private/users/{user_id}/role", response_model=UserRead)
async def change_role(
    user_id: str,
    data: AdminRoleUpdate,
    _admin: Annotated[User, Depends(require_platform_admin)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    user = await service.change_user_role(user_id, data)
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, user.id, storage)
    user_read = UserRead.model_validate(user)
    user_read.profile_photo = photo
    return user_read


@router.patch("/private/users/{user_id}/privilege", response_model=UserRead)
async def change_privilege(
    user_id: str,
    data: PrivilegeUpdate,
    _owner: Annotated[User, Depends(require_platform_owner)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    user = await service.change_privilege(user_id, data)
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, user.id, storage)
    user_read = UserRead.model_validate(user)
    user_read.profile_photo = photo
    return user_read
