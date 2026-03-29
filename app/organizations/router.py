from typing import Annotated

from dadata import Dadata
from fastapi import APIRouter, Depends, Response

from app.core.dependencies import require_active_user, require_platform_admin
from app.core.enums import MediaOwnerType
from app.media import service as media_service
from app.media.storage import StorageClient, get_storage
from app.organizations import service
from app.organizations.dependencies import get_dadata_client, get_org_or_404, require_org_admin, require_org_member
from app.organizations.models import Membership, Organization
from app.organizations.schemas import (
    ContactRead,
    ContactsReplace,
    MembershipApprove,
    MembershipInvite,
    MembershipRead,
    MembershipRoleUpdate,
    OrganizationCreate,
    OrganizationPhotoUpdate,
    OrganizationRead,
    PaymentDetailsCreate,
    PaymentDetailsRead,
)
from app.users.models import User

router = APIRouter()


@router.post("/organizations/", response_model=OrganizationRead)
async def create_organization(
    data: OrganizationCreate,
    user: Annotated[User, Depends(require_active_user)],
    dadata: Annotated[Dadata, Depends(get_dadata_client)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> OrganizationRead:
    org_read = await service.create_organization(data, user, dadata)
    org_read.photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org_read.id, storage)
    return org_read


@router.get("/organizations/{org_id}", response_model=OrganizationRead)
async def get_organization(
    org_id: str,
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> OrganizationRead:
    org_read = await service.get_organization(org_id)
    org_read.photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org_read.id, storage)
    return org_read


@router.get("/users/me/organizations", response_model=list[OrganizationRead])
async def list_my_organizations(
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> list[OrganizationRead]:
    orgs = await service.list_user_organizations(user)
    for org_read in orgs:
        org_read.photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org_read.id, storage)
    return orgs


@router.patch("/organizations/{org_id}/photo", response_model=OrganizationRead)
async def update_org_photo(
    data: OrganizationPhotoUpdate,
    membership: Annotated[Membership, Depends(require_org_admin)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> OrganizationRead:
    await membership.fetch_related("organization", "user")
    org: Organization = membership.organization
    user: User = membership.user
    await media_service.attach_profile_photo(
        data.photo_id,
        MediaOwnerType.ORGANIZATION,
        org.id,
        user,
        storage,
    )
    await org.fetch_related("contacts")
    org_read = OrganizationRead.model_validate(org)
    org_read.photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org.id, storage)
    return org_read


@router.put("/organizations/{org_id}/contacts", response_model=list[ContactRead])
async def replace_contacts(
    org_id: str,
    data: ContactsReplace,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> list[ContactRead]:
    return await service.replace_contacts(org_id, data)


@router.get("/organizations/{org_id}/payment-details", response_model=PaymentDetailsRead)
async def get_payment_details(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_member)],
) -> PaymentDetailsRead:
    return await service.get_payment_details(org_id)


@router.post("/organizations/{org_id}/payment-details", response_model=PaymentDetailsRead)
async def create_payment_details(
    org_id: str,
    data: PaymentDetailsCreate,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> PaymentDetailsRead:
    return await service.upsert_payment_details(org_id, data)


@router.post("/organizations/{org_id}/members/invite", response_model=MembershipRead)
async def invite_member(
    org_id: str,
    data: MembershipInvite,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> MembershipRead:
    return await service.invite_member(org_id, data)


@router.post("/organizations/{org_id}/members/join", response_model=MembershipRead)
async def join_organization(
    user: Annotated[User, Depends(require_active_user)],
    org: Annotated[Organization, Depends(get_org_or_404)],
) -> MembershipRead:
    return await service.join_organization(org.id, user)


@router.patch("/organizations/{org_id}/members/{member_id}/approve", response_model=MembershipRead)
async def approve_candidate(
    org_id: str,
    member_id: str,
    data: MembershipApprove,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> MembershipRead:
    return await service.approve_candidate(org_id, member_id, data)


@router.patch("/organizations/{org_id}/members/{member_id}/accept", response_model=MembershipRead)
async def accept_invitation(
    member_id: str,
    user: Annotated[User, Depends(require_active_user)],
    org: Annotated[Organization, Depends(get_org_or_404)],
) -> MembershipRead:
    return await service.accept_invitation(org.id, member_id, user)


@router.patch("/organizations/{org_id}/members/{member_id}/role", response_model=MembershipRead)
async def change_member_role(
    org_id: str,
    member_id: str,
    data: MembershipRoleUpdate,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> MembershipRead:
    return await service.change_member_role(org_id, member_id, data)


@router.delete("/organizations/{org_id}/members/{member_id}", status_code=204)
async def remove_member(
    member_id: str,
    user: Annotated[User, Depends(require_active_user)],
    org: Annotated[Organization, Depends(get_org_or_404)],
) -> Response:
    await service.remove_member(org.id, member_id, user)
    return Response(status_code=204)


@router.get("/organizations/{org_id}/members", response_model=list[MembershipRead])
async def list_members(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_member)],
) -> list[MembershipRead]:
    return await service.list_members(org_id)


@router.patch("/private/organizations/{org_id}/verify", response_model=OrganizationRead)
async def verify_organization(
    org_id: str,
    _admin: Annotated[User, Depends(require_platform_admin)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> OrganizationRead:
    org_read = await service.verify_organization(org_id)
    org_read.photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org_read.id, storage)
    return org_read
