from typing import Annotated

from dadata import Dadata
from fastapi import APIRouter, Depends

from app.core.dependencies import require_active_user, require_platform_admin
from app.organizations import service
from app.organizations.dependencies import get_dadata_client
from app.organizations.schemas import OrganizationCreate, OrganizationRead
from app.users.models import User

router = APIRouter()


@router.post("/organizations/", response_model=OrganizationRead)
async def create_organization(
    data: OrganizationCreate,
    user: Annotated[User, Depends(require_active_user)],
    dadata: Annotated[Dadata, Depends(get_dadata_client)],
) -> OrganizationRead:
    return await service.create_organization(data, user, dadata)


@router.get("/organizations/{org_id}", response_model=OrganizationRead)
async def get_organization(org_id: str) -> OrganizationRead:
    return await service.get_organization(org_id)


@router.get("/users/me/organizations", response_model=list[OrganizationRead])
async def list_my_organizations(
    user: Annotated[User, Depends(require_active_user)],
) -> list[OrganizationRead]:
    return await service.list_user_organizations(user)


@router.patch("/private/organizations/{org_id}/verify", response_model=OrganizationRead)
async def verify_organization(
    org_id: str,
    _admin: Annotated[User, Depends(require_platform_admin)],
) -> OrganizationRead:
    return await service.verify_organization(org_id)
