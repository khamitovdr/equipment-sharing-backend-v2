from tortoise.expressions import Q
from tortoise.functions import Count

from app.core.enums import ListingStatus, OrganizationStatus
from app.core.exceptions import NotFoundError
from app.core.identifiers import create_with_short_id
from app.listings.models import Listing, ListingCategory
from app.listings.schemas import (
    ListingCategoryCreate,
    ListingCategoryRead,
    ListingCreate,
    ListingRead,
)
from app.organizations.models import Organization
from app.users.models import User


async def _verified_org_ids() -> list[str]:
    orgs = await Organization.filter(status=OrganizationStatus.VERIFIED).only("id")
    return [org.id for org in orgs]


def _category_to_read(category: ListingCategory) -> ListingCategoryRead:
    return ListingCategoryRead(
        id=category.id,
        name=category.name,
        verified=category.verified,
        created_at=category.created_at,
        listing_count=getattr(category, "listing_count", 0),
    )


async def create_category(org: Organization, user: User, data: ListingCategoryCreate) -> ListingCategoryRead:
    category = await create_with_short_id(
        ListingCategory,
        name=data.name,
        organization=org,
        added_by=user,
        verified=False,
    )
    return ListingCategoryRead(
        id=category.id,
        name=category.name,
        verified=category.verified,
        created_at=category.created_at,
        listing_count=0,
    )


async def list_public_categories() -> list[ListingCategoryRead]:
    verified_org_ids = await _verified_org_ids()
    categories = (
        await ListingCategory.filter(verified=True)
        .annotate(
            listing_count=Count(
                "listings",
                _filter=Q(
                    listings__status=ListingStatus.PUBLISHED,
                    listings__organization_id__in=verified_org_ids,
                ),
            ),
        )
        .order_by("-listing_count")
    )
    return [_category_to_read(c) for c in categories]


async def _validate_category(category_id: str, org: Organization) -> ListingCategory:
    category = await ListingCategory.get_or_none(id=category_id)
    if category is None:
        raise NotFoundError("Category not found")
    if not category.verified:
        owned = await ListingCategory.filter(id=category_id, organization_id=org.id).exists()
        if not owned:
            raise NotFoundError("Category not found")
    return category


async def create_listing(org: Organization, user: User, data: ListingCreate) -> ListingRead:
    category = await _validate_category(data.category_id, org)
    listing = await create_with_short_id(
        Listing,
        name=data.name,
        category=category,
        price=data.price,
        description=data.description,
        specifications=data.specifications,
        organization=org,
        added_by=user,
        with_operator=data.with_operator,
        on_owner_site=data.on_owner_site,
        delivery=data.delivery,
        installation=data.installation,
        setup=data.setup,
    )
    await listing.fetch_related("category")
    return ListingRead.model_validate(listing)


async def list_org_categories(org_id: str) -> list[ListingCategoryRead]:
    org_categories = (
        await ListingCategory.filter(listings__organization_id=org_id)
        .annotate(
            listing_count=Count(
                "listings",
                _filter=Q(listings__organization_id=org_id),
            ),
        )
        .distinct()
    )
    verified_ids = {c.id for c in org_categories}
    global_categories = (
        await ListingCategory.filter(verified=True)
        .exclude(id__in=verified_ids or {"__none__"})
        .annotate(
            listing_count=Count(
                "listings",
                _filter=Q(listings__organization_id=org_id),
            ),
        )
    )
    all_categories = list(org_categories) + list(global_categories)
    all_categories.sort(key=lambda c: getattr(c, "listing_count", 0), reverse=True)
    return [_category_to_read(c) for c in all_categories]
