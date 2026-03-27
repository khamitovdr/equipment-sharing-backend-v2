# Organization Business Logic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full Organization section from the business-logic spec: org CRUD with Dadata integration, contacts management, payment details, membership system, and verification.

**Architecture:** Single-module approach — all org logic in `app/organizations/` (schemas, service, router, dependencies). Dadata client injected via FastAPI dependency. Org-level permissions checked via dedicated dependencies that verify membership role + status.

**Tech Stack:** FastAPI, Tortoise ORM, Pydantic v2, dadata-py (sync client via `asyncio.to_thread`), pytest + httpx AsyncClient

**Design spec:** `docs/superpowers/specs/2026-03-27-organization-business-logic-design.md`

---

### Task 1: Foundation Changes

**Files:**
- Modify: `app/organizations/models.py` — replace contact name fields with `display_name`
- Modify: `app/core/exceptions.py` — add `ExternalServiceError` (502)
- Create: `app/organizations/dependencies.py` — Dadata dependency + org permission dependencies
- Create: `app/organizations/schemas.py` — empty file (placeholder)
- Create: `app/organizations/service.py` — empty file (placeholder)
- Create: `app/organizations/router.py` — empty router
- Modify: `app/main.py` — register organizations router

- [ ] **Step 1: Update OrganizationContact model**

Replace the three name fields with `display_name` in `app/organizations/models.py`:

```python
class OrganizationContact(Model):
    id = fields.UUIDField(primary_key=True)
    organization: Any = fields.ForeignKeyField("models.Organization", related_name="contacts")
    display_name = fields.CharField(max_length=255)
    phone = fields.CharField(max_length=255, null=True)
    email = fields.CharField(max_length=255, null=True)

    class Meta:
        table = "organization_contacts"
```

- [ ] **Step 2: Add ExternalServiceError**

In `app/core/exceptions.py`, add after `IDGenerationError`:

```python
class ExternalServiceError(AppError):
    pass
```

Add to `_STATUS_MAP`:

```python
ExternalServiceError: 502,
```

- [ ] **Step 3: Change AppValidationError status to 400**

In `app/core/exceptions.py`, update the `_STATUS_MAP` entry:

```python
AppValidationError: 400,
```

(Was 422. Pydantic handles 422 for schema validation; 400 is correct for business logic validation errors like wrong membership status.)

- [ ] **Step 4: Create org dependencies**

Create `app/organizations/dependencies.py`:

```python
from typing import Annotated

from dadata import Dadata
from fastapi import Depends, Path

from app.core.config import get_settings
from app.core.enums import MembershipRole, MembershipStatus
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.core.dependencies import require_active_user
from app.organizations.models import Membership, Organization
from app.users.models import User


def get_dadata_client() -> Dadata:
    settings = get_settings()
    return Dadata(settings.dadata_api_key)


async def _get_org_or_404(org_id: str = Path()) -> Organization:
    org = await Organization.get_or_none(id=org_id)
    if org is None:
        raise NotFoundError("Organization not found")
    return org


async def require_org_member(
    org: Annotated[Organization, Depends(_get_org_or_404)],
    user: Annotated[User, Depends(require_active_user)],
) -> Membership:
    membership = await Membership.get_or_none(
        organization=org,
        user=user,
        status=MembershipStatus.MEMBER,
    )
    if membership is None:
        raise PermissionDeniedError("Organization membership required")
    return membership


async def require_org_editor(
    org: Annotated[Organization, Depends(_get_org_or_404)],
    user: Annotated[User, Depends(require_active_user)],
) -> Membership:
    membership = await Membership.get_or_none(
        organization=org,
        user=user,
        status=MembershipStatus.MEMBER,
        role__in=[MembershipRole.ADMIN, MembershipRole.EDITOR],
    )
    if membership is None:
        raise PermissionDeniedError("Organization editor access required")
    return membership


async def require_org_admin(
    org: Annotated[Organization, Depends(_get_org_or_404)],
    user: Annotated[User, Depends(require_active_user)],
) -> Membership:
    membership = await Membership.get_or_none(
        organization=org,
        user=user,
        status=MembershipStatus.MEMBER,
        role=MembershipRole.ADMIN,
    )
    if membership is None:
        raise PermissionDeniedError("Organization admin access required")
    return membership
```

- [ ] **Step 5: Create empty router and wire up**

Create `app/organizations/schemas.py` (empty for now):

```python
```

Create `app/organizations/service.py` (empty for now):

```python
```

Create `app/organizations/router.py`:

```python
from fastapi import APIRouter

router = APIRouter()
```

Update `app/main.py` — add import and include router. After the `users_router` import, add:

```python
from app.organizations.router import router as organizations_router
```

After `application.include_router(users_router)`, add:

```python
application.include_router(organizations_router)
```

- [ ] **Step 6: Verify the app starts**

Run: `task lint:fix && task typecheck`
Expected: No errors (empty modules are valid)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(organizations): foundation — model update, errors, dependencies, router skeleton"
```

---

### Task 2: Schemas

**Files:**
- Create: `app/organizations/schemas.py`

- [ ] **Step 1: Write all schemas**

Write `app/organizations/schemas.py`:

```python
import re
from datetime import datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator, model_validator

from app.core.enums import MembershipRole, MembershipStatus, OrganizationStatus

_INN_RE = re.compile(r"^\d{10}$|^\d{12}$")


class ContactCreate(BaseModel):
    display_name: str
    phone: str | None = None
    email: EmailStr | None = None

    @model_validator(mode="after")
    def at_least_one_contact_method(self) -> Self:
        if not self.phone and not self.email:
            msg = "At least one of phone or email must be provided"
            raise ValueError(msg)
        return self


class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str
    phone: str | None
    email: str | None


class OrganizationCreate(BaseModel):
    inn: str
    contacts: list[ContactCreate]

    @field_validator("inn")
    @classmethod
    def inn_format(cls, v: str) -> str:
        if not _INN_RE.match(v):
            msg = "INN must be 10 or 12 digits"
            raise ValueError(msg)
        return v

    @field_validator("contacts")
    @classmethod
    def at_least_one_contact(cls, v: list[ContactCreate]) -> list[ContactCreate]:
        if not v:
            msg = "At least one contact is required"
            raise ValueError(msg)
        return v


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    inn: str
    short_name: str | None
    full_name: str | None
    registration_date: str | None
    authorized_capital_k_rubles: Decimal | None
    legal_address: str | None
    manager_name: str | None
    main_activity: str | None
    status: OrganizationStatus
    contacts: list[ContactRead]


class ContactsReplace(BaseModel):
    contacts: list[ContactCreate]

    @field_validator("contacts")
    @classmethod
    def at_least_one_contact(cls, v: list[ContactCreate]) -> list[ContactCreate]:
        if not v:
            msg = "At least one contact is required"
            raise ValueError(msg)
        return v


class PaymentDetailsCreate(BaseModel):
    payment_account: str
    bank_bic: str
    bank_inn: str
    bank_name: str
    bank_correspondent_account: str


class PaymentDetailsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payment_account: str
    bank_bic: str
    bank_inn: str
    bank_name: str
    bank_correspondent_account: str


class MembershipInvite(BaseModel):
    user_id: str
    role: MembershipRole


class MembershipApprove(BaseModel):
    role: MembershipRole


class MembershipRoleUpdate(BaseModel):
    role: MembershipRole


class MembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: str
    organization_id: str
    role: MembershipRole
    status: MembershipStatus
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 2: Lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add app/organizations/schemas.py
git commit -m "feat(organizations): add Pydantic schemas for org, contacts, payments, membership"
```

---

### Task 3: Organization Creation

**Files:**
- Modify: `app/organizations/service.py`
- Modify: `app/organizations/router.py`
- Modify: `tests/conftest.py` — add Dadata mock fixture and org creation helper
- Create: `tests/test_organizations.py`

- [ ] **Step 1: Add test fixtures to conftest.py**

Add these imports at the top of `tests/conftest.py`:

```python
from unittest.mock import MagicMock

from app.organizations.dependencies import get_dadata_client
```

Add the Dadata mock response constant after `_TEST_TABLES`:

```python
DADATA_PARTY_RESPONSE = {
    "value": 'ООО "РОГА И КОПЫТА"',
    "data": {
        "inn": "7707083893",
        "name": {
            "short_with_opf": 'ООО "Рога и копыта"',
            "full_with_opf": 'ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "РОГА И КОПЫТА"',
        },
        "state": {
            "registration_date": 1029456000000,
        },
        "address": {
            "value": "г Москва, ул Ленина, д 1",
        },
        "management": {
            "name": "Иванов Иван Иванович",
        },
        "okved": "62.01",
    },
}
```

Add fixtures after `owner_user`:

```python
@pytest.fixture(autouse=True)
def mock_dadata(client: AsyncClient) -> MagicMock:
    mock = MagicMock()
    mock.find_by_id.return_value = [DADATA_PARTY_RESPONSE]
    app.dependency_overrides[get_dadata_client] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_dadata_client, None)


def _default_org_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "inn": "7707083893",
        "contacts": [
            {
                "display_name": "Иван Иванов",
                "phone": "+79991234567",
                "email": "contact@example.com",
            },
        ],
    }
    data.update(overrides)
    return data


@pytest.fixture
async def create_organization(client: AsyncClient, create_user: Any) -> Any:
    async def _create(
        token: str | None = None,
        **overrides: Any,
    ) -> tuple[dict[str, Any], str]:
        if token is None:
            _, token = await create_user(email="orgcreator@example.com")
        data = _default_org_data(**overrides)
        resp = await client.post(
            "/organizations/",
            json=data,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        return resp.json(), token

    return _create
```

- [ ] **Step 2: Write failing tests for org creation**

Create `tests/test_organizations.py`:

```python
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from tests.conftest import _default_org_data


class TestCreateOrganization:
    async def test_create_org_success(
        self,
        client: AsyncClient,
        create_user: Any,
        mock_dadata: MagicMock,
    ) -> None:
        _, token = await create_user()
        data = _default_org_data()
        resp = await client.post(
            "/organizations/",
            json=data,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["inn"] == "7707083893"
        assert body["short_name"] == 'ООО "Рога и копыта"'
        assert body["status"] == "created"
        assert len(body["contacts"]) == 1
        assert body["contacts"][0]["display_name"] == "Иван Иванов"
        mock_dadata.find_by_id.assert_called_once_with("party", "7707083893")

    async def test_create_org_creator_becomes_admin(
        self,
        client: AsyncClient,
        create_user: Any,
    ) -> None:
        _, token = await create_user()
        data = _default_org_data()
        resp = await client.post(
            "/organizations/",
            json=data,
            headers={"Authorization": f"Bearer {token}"},
        )
        org_id = resp.json()["id"]
        members_resp = await client.get(
            f"/organizations/{org_id}/members",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert members_resp.status_code == 200
        members = members_resp.json()
        assert len(members) == 1
        assert members[0]["role"] == "admin"
        assert members[0]["status"] == "member"

    async def test_create_org_duplicate_inn(
        self,
        client: AsyncClient,
        create_user: Any,
    ) -> None:
        user1_data, token1 = await create_user()
        _, token2 = await create_user(email="other@example.com")
        data = _default_org_data()
        await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token1}"})
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token2}"})
        assert resp.status_code == 409

    async def test_create_org_invalid_inn(self, client: AsyncClient, create_user: Any) -> None:
        _, token = await create_user()
        data = _default_org_data(inn="123")
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 422

    async def test_create_org_no_contacts(self, client: AsyncClient, create_user: Any) -> None:
        _, token = await create_user()
        data = _default_org_data(contacts=[])
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 422

    async def test_create_org_contact_missing_phone_and_email(
        self,
        client: AsyncClient,
        create_user: Any,
    ) -> None:
        _, token = await create_user()
        data = _default_org_data(contacts=[{"display_name": "Test"}])
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 422

    async def test_create_org_dadata_failure(
        self,
        client: AsyncClient,
        create_user: Any,
        mock_dadata: MagicMock,
    ) -> None:
        mock_dadata.find_by_id.side_effect = Exception("Dadata unavailable")
        _, token = await create_user()
        data = _default_org_data()
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 502

    async def test_create_org_dadata_empty(
        self,
        client: AsyncClient,
        create_user: Any,
        mock_dadata: MagicMock,
    ) -> None:
        mock_dadata.find_by_id.return_value = []
        _, token = await create_user()
        data = _default_org_data()
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 502

    async def test_create_org_unauthenticated(self, client: AsyncClient) -> None:
        data = _default_org_data()
        resp = await client.post("/organizations/", json=data)
        assert resp.status_code == 401
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `task test -- tests/test_organizations.py::TestCreateOrganization -v`
Expected: FAIL (no routes defined yet)

- [ ] **Step 4: Implement org creation service**

Write `app/organizations/service.py`:

```python
import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from dadata import Dadata
from tortoise.transactions import in_transaction

from app.core.enums import MembershipRole, MembershipStatus
from app.core.exceptions import AlreadyExistsError, ExternalServiceError
from app.core.identifiers import create_with_short_id
from app.organizations.models import Membership, Organization, OrganizationContact
from app.organizations.schemas import OrganizationCreate, OrganizationRead
from app.users.models import User


def _extract_dadata_fields(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data", {})
    name = data.get("name", {})
    state = data.get("state", {})
    address = data.get("address", {})
    management = data.get("management", {})

    reg_date = None
    reg_ts = state.get("registration_date")
    if reg_ts is not None:
        reg_date = datetime.fromtimestamp(reg_ts / 1000, tz=UTC).date()

    return {
        "short_name": name.get("short_with_opf"),
        "full_name": name.get("full_with_opf"),
        "registration_date": reg_date,
        "legal_address": address.get("value"),
        "manager_name": management.get("name"),
        "main_activity": data.get("okved"),
    }


async def create_organization(
    data: OrganizationCreate,
    user: User,
    dadata: Dadata,
) -> OrganizationRead:
    existing = await Organization.filter(inn=data.inn).exists()
    if existing:
        raise AlreadyExistsError("Organization with this INN already exists")

    try:
        results = await asyncio.to_thread(dadata.find_by_id, "party", data.inn)
    except Exception as e:
        raise ExternalServiceError("Dadata service unavailable") from e

    if not results:
        raise ExternalServiceError("Organization not found by INN")

    dadata_result = results[0]
    dadata_fields = _extract_dadata_fields(dadata_result)

    async with in_transaction():
        org = await create_with_short_id(
            Organization,
            inn=data.inn,
            dadata_response=dadata_result,
            **dadata_fields,
        )

        for contact in data.contacts:
            await OrganizationContact.create(
                id=uuid4(),
                organization=org,
                display_name=contact.display_name,
                phone=contact.phone,
                email=contact.email,
            )

        await Membership.create(
            id=uuid4(),
            user=user,
            organization=org,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.MEMBER,
        )

    await org.fetch_related("contacts")
    return OrganizationRead.model_validate(org)
```

- [ ] **Step 5: Add creation endpoint to router**

Update `app/organizations/router.py`:

```python
from typing import Annotated

from dadata import Dadata
from fastapi import APIRouter, Depends

from app.core.dependencies import require_active_user
from app.organizations import service
from app.organizations.dependencies import get_dadata_client
from app.organizations.schemas import OrganizationRead
from app.organizations.schemas import OrganizationCreate
from app.users.models import User

router = APIRouter()


@router.post("/organizations/", response_model=OrganizationRead)
async def create_organization(
    data: OrganizationCreate,
    user: Annotated[User, Depends(require_active_user)],
    dadata: Annotated[Dadata, Depends(get_dadata_client)],
) -> OrganizationRead:
    return await service.create_organization(data, user, dadata)
```

- [ ] **Step 6: Run creation tests**

Run: `task test -- tests/test_organizations.py::TestCreateOrganization -v`
Expected: Most pass. `test_create_org_creator_becomes_admin` may fail (needs list members endpoint — skip for now and move it to Task 9). If so, mark it with `pytest.mark.skip(reason="needs list members endpoint")` temporarily.

- [ ] **Step 7: Lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(organizations): org creation with Dadata integration and tests"
```

---

### Task 4: Organization Read, List, and Verify

**Files:**
- Modify: `app/organizations/service.py`
- Modify: `app/organizations/router.py`
- Modify: `tests/test_organizations.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_organizations.py`:

```python
class TestGetOrganization:
    async def test_get_org_by_id(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, _ = await create_organization()
        resp = await client.get(f"/organizations/{org_data['id']}")
        assert resp.status_code == 200
        assert resp.json()["inn"] == "7707083893"
        assert len(resp.json()["contacts"]) == 1

    async def test_get_org_not_found(self, client: AsyncClient) -> None:
        resp = await client.get("/organizations/ZZZZZZ")
        assert resp.status_code == 404


class TestListUserOrganizations:
    async def test_list_my_orgs(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        resp = await client.get(
            "/users/me/organizations",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        orgs = resp.json()
        assert len(orgs) == 1
        assert orgs[0]["id"] == org_data["id"]

    async def test_list_my_orgs_empty(
        self,
        client: AsyncClient,
        create_user: Any,
    ) -> None:
        _, token = await create_user()
        resp = await client.get(
            "/users/me/organizations",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_my_orgs_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/users/me/organizations")
        assert resp.status_code == 401


class TestVerifyOrganization:
    async def test_verify_org(
        self,
        client: AsyncClient,
        create_organization: Any,
        admin_user: tuple[dict[str, Any], str],
    ) -> None:
        org_data, _ = await create_organization()
        _, admin_token = admin_user
        resp = await client.patch(
            f"/private/organizations/{org_data['id']}/verify",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "verified"

    async def test_verify_org_idempotent(
        self,
        client: AsyncClient,
        create_organization: Any,
        admin_user: tuple[dict[str, Any], str],
    ) -> None:
        org_data, _ = await create_organization()
        _, admin_token = admin_user
        await client.patch(
            f"/private/organizations/{org_data['id']}/verify",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        resp = await client.patch(
            f"/private/organizations/{org_data['id']}/verify",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "verified"

    async def test_verify_org_not_admin(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        resp = await client.patch(
            f"/private/organizations/{org_data['id']}/verify",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_verify_org_not_found(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
    ) -> None:
        _, admin_token = admin_user
        resp = await client.patch(
            "/private/organizations/ZZZZZZ/verify",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `task test -- tests/test_organizations.py::TestGetOrganization tests/test_organizations.py::TestListUserOrganizations tests/test_organizations.py::TestVerifyOrganization -v`
Expected: FAIL

- [ ] **Step 3: Implement service functions**

Add to `app/organizations/service.py`:

```python
from app.core.enums import MembershipStatus, OrganizationStatus
from app.core.exceptions import NotFoundError


async def get_organization(org_id: str) -> OrganizationRead:
    org = await Organization.get_or_none(id=org_id).prefetch_related("contacts")
    if org is None:
        raise NotFoundError("Organization not found")
    return OrganizationRead.model_validate(org)


async def list_user_organizations(user: User) -> list[OrganizationRead]:
    memberships = await Membership.filter(
        user=user,
        status=MembershipStatus.MEMBER,
    ).prefetch_related("organization__contacts")
    return [OrganizationRead.model_validate(m.organization) for m in memberships]


async def verify_organization(org_id: str) -> OrganizationRead:
    org = await Organization.get_or_none(id=org_id)
    if org is None:
        raise NotFoundError("Organization not found")
    org.status = OrganizationStatus.VERIFIED
    await org.save()
    await org.fetch_related("contacts")
    return OrganizationRead.model_validate(org)
```

- [ ] **Step 4: Add router endpoints**

Add to `app/organizations/router.py`:

```python
from app.core.dependencies import require_active_user, require_platform_admin


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
```

- [ ] **Step 5: Run tests**

Run: `task test -- tests/test_organizations.py::TestGetOrganization tests/test_organizations.py::TestListUserOrganizations tests/test_organizations.py::TestVerifyOrganization -v`
Expected: PASS

- [ ] **Step 6: Lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(organizations): get, list user orgs, and verify endpoints with tests"
```

---

### Task 5: Contacts Replacement

**Files:**
- Modify: `app/organizations/service.py`
- Modify: `app/organizations/router.py`
- Modify: `tests/test_organizations.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_organizations.py`:

```python
class TestReplaceContacts:
    async def test_replace_contacts(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        new_contacts = {
            "contacts": [
                {"display_name": "Новый контакт", "phone": "+79998887766"},
                {"display_name": "Отдел аренды", "email": "rent@example.com"},
            ],
        }
        resp = await client.put(
            f"/organizations/{org_data['id']}/contacts",
            json=new_contacts,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        contacts = resp.json()
        assert len(contacts) == 2
        assert contacts[0]["display_name"] == "Новый контакт"
        assert contacts[1]["display_name"] == "Отдел аренды"

    async def test_replace_contacts_empty_list(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        resp = await client.put(
            f"/organizations/{org_data['id']}/contacts",
            json={"contacts": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    async def test_replace_contacts_not_admin(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, _ = await create_organization()
        _, other_token = await create_user(email="other@example.com")
        resp = await client.put(
            f"/organizations/{org_data['id']}/contacts",
            json={"contacts": [{"display_name": "Test", "phone": "+79991112233"}]},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403

    async def test_replace_contacts_org_not_found(
        self,
        client: AsyncClient,
        create_user: Any,
    ) -> None:
        _, token = await create_user()
        resp = await client.put(
            "/organizations/ZZZZZZ/contacts",
            json={"contacts": [{"display_name": "Test", "phone": "+79991112233"}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `task test -- tests/test_organizations.py::TestReplaceContacts -v`
Expected: FAIL

- [ ] **Step 3: Implement service function**

Add to `app/organizations/service.py`:

```python
from app.organizations.schemas import ContactRead, ContactsReplace


async def replace_contacts(org: Organization, data: ContactsReplace) -> list[ContactRead]:
    async with in_transaction():
        await OrganizationContact.filter(organization=org).delete()
        for contact in data.contacts:
            await OrganizationContact.create(
                id=uuid4(),
                organization=org,
                display_name=contact.display_name,
                phone=contact.phone,
                email=contact.email,
            )
    contacts = await OrganizationContact.filter(organization=org)
    return [ContactRead.model_validate(c) for c in contacts]
```

- [ ] **Step 4: Add router endpoint**

Add to `app/organizations/router.py`:

```python
from app.organizations.dependencies import require_org_admin
from app.organizations.schemas import ContactRead, ContactsReplace
from app.organizations.models import Membership, Organization


@router.put("/organizations/{org_id}/contacts", response_model=list[ContactRead])
async def replace_contacts(
    data: ContactsReplace,
    membership: Annotated[Membership, Depends(require_org_admin)],
) -> list[ContactRead]:
    return await service.replace_contacts(membership.organization, data)
```

Note: `require_org_admin` resolves the org internally via `_get_org_or_404`. Access the org via `membership.organization`. However, Tortoise may not have the `organization` loaded. We need to ensure it's available. Two options:

Option A: Fetch the org from membership in the service. Update the service to accept `Membership` and fetch `organization`:

```python
async def replace_contacts(membership: Membership, data: ContactsReplace) -> list[ContactRead]:
    org = await Organization.get(id=membership.organization_id)
    ...
```

Option B: The dependency already loads the org. We pass the org_id. Update the router:

```python
@router.put("/organizations/{org_id}/contacts", response_model=list[ContactRead])
async def replace_contacts(
    org_id: str,
    data: ContactsReplace,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> list[ContactRead]:
    return await service.replace_contacts(org_id, data)
```

And update the service:

```python
async def replace_contacts(org_id: str, data: ContactsReplace) -> list[ContactRead]:
    async with in_transaction():
        await OrganizationContact.filter(organization_id=org_id).delete()
        for contact in data.contacts:
            await OrganizationContact.create(
                id=uuid4(),
                organization_id=org_id,
                display_name=contact.display_name,
                phone=contact.phone,
                email=contact.email,
            )
    contacts = await OrganizationContact.filter(organization_id=org_id)
    return [ContactRead.model_validate(c) for c in contacts]
```

Use Option B — it's simpler and avoids loading the org object. The dependency already verified the org exists and the user is admin.

- [ ] **Step 5: Run tests**

Run: `task test -- tests/test_organizations.py::TestReplaceContacts -v`
Expected: PASS

- [ ] **Step 6: Lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(organizations): contacts replacement endpoint with tests"
```

---

### Task 6: Payment Details

**Files:**
- Modify: `app/organizations/service.py`
- Modify: `app/organizations/router.py`
- Modify: `tests/test_organizations.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_organizations.py`:

```python
_PAYMENT_DATA = {
    "payment_account": "40702810000000000001",
    "bank_bic": "044525225",
    "bank_inn": "7707083893",
    "bank_name": "ПАО Сбербанк",
    "bank_correspondent_account": "30101810400000000225",
}


class TestPaymentDetails:
    async def test_create_payment_details(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        resp = await client.post(
            f"/organizations/{org_data['id']}/payment-details",
            json=_PAYMENT_DATA,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["payment_account"] == "40702810000000000001"
        assert body["bank_name"] == "ПАО Сбербанк"
        assert "id" in body

    async def test_upsert_payment_details(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        await client.post(
            f"/organizations/{org_data['id']}/payment-details",
            json=_PAYMENT_DATA,
            headers={"Authorization": f"Bearer {token}"},
        )
        updated = {**_PAYMENT_DATA, "bank_name": "АО Тинькофф Банк"}
        resp = await client.post(
            f"/organizations/{org_data['id']}/payment-details",
            json=updated,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["bank_name"] == "АО Тинькофф Банк"

    async def test_get_payment_details(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        await client.post(
            f"/organizations/{org_data['id']}/payment-details",
            json=_PAYMENT_DATA,
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = await client.get(
            f"/organizations/{org_data['id']}/payment-details",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["bank_name"] == "ПАО Сбербанк"

    async def test_get_payment_details_not_set(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, token = await create_organization()
        resp = await client.get(
            f"/organizations/{org_data['id']}/payment-details",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    async def test_create_payment_details_not_admin(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, _ = await create_organization()
        _, other_token = await create_user(email="other@example.com")
        resp = await client.post(
            f"/organizations/{org_data['id']}/payment-details",
            json=_PAYMENT_DATA,
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `task test -- tests/test_organizations.py::TestPaymentDetails -v`
Expected: FAIL

- [ ] **Step 3: Implement service functions**

Add to `app/organizations/service.py`:

```python
from app.organizations.models import PaymentDetails
from app.organizations.schemas import PaymentDetailsCreate, PaymentDetailsRead


async def get_payment_details(org_id: str) -> PaymentDetailsRead:
    pd = await PaymentDetails.get_or_none(organization_id=org_id)
    if pd is None:
        raise NotFoundError("Payment details not found")
    return PaymentDetailsRead.model_validate(pd)


async def upsert_payment_details(org_id: str, data: PaymentDetailsCreate) -> PaymentDetailsRead:
    pd = await PaymentDetails.get_or_none(organization_id=org_id)
    if pd is None:
        pd = await PaymentDetails.create(
            id=uuid4(),
            organization_id=org_id,
            **data.model_dump(),
        )
    else:
        for field, value in data.model_dump().items():
            setattr(pd, field, value)
        await pd.save()
    return PaymentDetailsRead.model_validate(pd)
```

- [ ] **Step 4: Add router endpoints**

Add to `app/organizations/router.py`:

```python
from app.organizations.dependencies import require_org_member
from app.organizations.schemas import PaymentDetailsCreate, PaymentDetailsRead


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
```

- [ ] **Step 5: Run tests**

Run: `task test -- tests/test_organizations.py::TestPaymentDetails -v`
Expected: PASS

- [ ] **Step 6: Lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(organizations): payment details get and upsert endpoints with tests"
```

---

### Task 7: Membership — Invite and Join

**Files:**
- Modify: `app/organizations/service.py`
- Modify: `app/organizations/router.py`
- Modify: `tests/test_organizations.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_organizations.py`:

```python
class TestMembershipInvite:
    async def test_invite_user(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        user_data, _ = await create_user(email="invitee@example.com")
        resp = await client.post(
            f"/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == user_data["id"]
        assert body["role"] == "editor"
        assert body["status"] == "invited"

    async def test_invite_nonexistent_user(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        resp = await client.post(
            f"/organizations/{org_data['id']}/members/invite",
            json={"user_id": "ZZZZZZ", "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    async def test_invite_duplicate(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        user_data, _ = await create_user(email="invitee@example.com")
        await client.post(
            f"/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        resp = await client.post(
            f"/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "viewer"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409

    async def test_invite_not_admin(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, _ = await create_organization()
        _, other_token = await create_user(email="nonadmin@example.com")
        user_data, _ = await create_user(email="invitee@example.com")
        resp = await client.post(
            f"/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403


class TestMembershipJoin:
    async def test_join_request(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, _ = await create_organization()
        _, user_token = await create_user(email="joiner@example.com")
        resp = await client.post(
            f"/organizations/{org_data['id']}/members/join",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "viewer"
        assert body["status"] == "candidate"

    async def test_join_duplicate(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, _ = await create_organization()
        _, user_token = await create_user(email="joiner@example.com")
        await client.post(
            f"/organizations/{org_data['id']}/members/join",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp = await client.post(
            f"/organizations/{org_data['id']}/members/join",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 409

    async def test_join_already_member(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        resp = await client.post(
            f"/organizations/{org_data['id']}/members/join",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `task test -- tests/test_organizations.py::TestMembershipInvite tests/test_organizations.py::TestMembershipJoin -v`
Expected: FAIL

- [ ] **Step 3: Implement service functions**

Add to `app/organizations/service.py`:

```python
from app.core.exceptions import AppValidationError
from app.organizations.schemas import MembershipInvite, MembershipRead


async def invite_member(org_id: str, data: MembershipInvite) -> MembershipRead:
    target_user = await User.get_or_none(id=data.user_id)
    if target_user is None:
        raise NotFoundError("User not found")

    existing = await Membership.get_or_none(user=target_user, organization_id=org_id)
    if existing is not None:
        raise AlreadyExistsError("User already has a membership in this organization")

    membership = await Membership.create(
        id=uuid4(),
        user=target_user,
        organization_id=org_id,
        role=data.role,
        status=MembershipStatus.INVITED,
    )
    return MembershipRead.model_validate(membership)


async def join_organization(org_id: str, user: User) -> MembershipRead:
    existing = await Membership.get_or_none(user=user, organization_id=org_id)
    if existing is not None:
        raise AlreadyExistsError("You already have a membership in this organization")

    membership = await Membership.create(
        id=uuid4(),
        user=user,
        organization_id=org_id,
        role=MembershipRole.VIEWER,
        status=MembershipStatus.CANDIDATE,
    )
    return MembershipRead.model_validate(membership)
```

- [ ] **Step 4: Add router endpoints**

Add to `app/organizations/router.py`:

```python
from app.organizations.schemas import MembershipInvite, MembershipRead


@router.post("/organizations/{org_id}/members/invite", response_model=MembershipRead)
async def invite_member(
    org_id: str,
    data: MembershipInvite,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> MembershipRead:
    return await service.invite_member(org_id, data)


@router.post("/organizations/{org_id}/members/join", response_model=MembershipRead)
async def join_organization(
    org_id: str,
    user: Annotated[User, Depends(require_active_user)],
) -> MembershipRead:
    # Verify org exists
    org = await Organization.get_or_none(id=org_id)
    if org is None:
        raise NotFoundError("Organization not found")
    return await service.join_organization(org_id, user)
```

Note: `join` uses `require_active_user` (not org member), so we manually check org existence.

Add the missing import to the router:

```python
from app.core.exceptions import NotFoundError
from app.organizations.models import Organization
```

- [ ] **Step 5: Run tests**

Run: `task test -- tests/test_organizations.py::TestMembershipInvite tests/test_organizations.py::TestMembershipJoin -v`
Expected: PASS

- [ ] **Step 6: Lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(organizations): membership invite and join endpoints with tests"
```

---

### Task 8: Membership — Approve and Accept

**Files:**
- Modify: `app/organizations/service.py`
- Modify: `app/organizations/router.py`
- Modify: `tests/test_organizations.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_organizations.py`:

```python
class TestMembershipApprove:
    async def test_approve_candidate(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        _, user_token = await create_user(email="joiner@example.com")
        join_resp = await client.post(
            f"/organizations/{org_data['id']}/members/join",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        member_id = join_resp.json()["id"]
        resp = await client.patch(
            f"/organizations/{org_data['id']}/members/{member_id}/approve",
            json={"role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "editor"
        assert resp.json()["status"] == "member"

    async def test_approve_wrong_status(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        user_data, _ = await create_user(email="invitee@example.com")
        invite_resp = await client.post(
            f"/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        resp = await client.patch(
            f"/organizations/{org_data['id']}/members/{member_id}/approve",
            json={"role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400

    async def test_approve_not_admin(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, _ = await create_organization()
        _, user_token = await create_user(email="joiner@example.com")
        join_resp = await client.post(
            f"/organizations/{org_data['id']}/members/join",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        member_id = join_resp.json()["id"]
        resp = await client.patch(
            f"/organizations/{org_data['id']}/members/{member_id}/approve",
            json={"role": "editor"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403


class TestMembershipAccept:
    async def test_accept_invitation(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        user_data, user_token = await create_user(email="invitee@example.com")
        invite_resp = await client.post(
            f"/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        resp = await client.patch(
            f"/organizations/{org_data['id']}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "member"
        assert resp.json()["role"] == "editor"

    async def test_accept_wrong_user(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        user_data, _ = await create_user(email="invitee@example.com")
        _, other_token = await create_user(email="other@example.com")
        invite_resp = await client.post(
            f"/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        resp = await client.patch(
            f"/organizations/{org_data['id']}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403

    async def test_accept_wrong_status(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        _, user_token = await create_user(email="joiner@example.com")
        join_resp = await client.post(
            f"/organizations/{org_data['id']}/members/join",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        member_id = join_resp.json()["id"]
        resp = await client.patch(
            f"/organizations/{org_data['id']}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `task test -- tests/test_organizations.py::TestMembershipApprove tests/test_organizations.py::TestMembershipAccept -v`
Expected: FAIL

- [ ] **Step 3: Implement service functions**

Add to `app/organizations/service.py`:

```python
from app.organizations.schemas import MembershipApprove


async def approve_candidate(org_id: str, member_id: str, data: MembershipApprove) -> MembershipRead:
    membership = await Membership.get_or_none(id=member_id, organization_id=org_id)
    if membership is None:
        raise NotFoundError("Membership not found")
    if membership.status != MembershipStatus.CANDIDATE:
        raise AppValidationError("Only candidates can be approved")
    membership.role = data.role
    membership.status = MembershipStatus.MEMBER
    await membership.save()
    return MembershipRead.model_validate(membership)


async def accept_invitation(org_id: str, member_id: str, user: User) -> MembershipRead:
    membership = await Membership.get_or_none(id=member_id, organization_id=org_id)
    if membership is None:
        raise NotFoundError("Membership not found")
    if membership.user_id != user.id:
        raise PermissionDeniedError("You can only accept your own invitation")
    if membership.status != MembershipStatus.INVITED:
        raise AppValidationError("Only invitations can be accepted")
    membership.status = MembershipStatus.MEMBER
    await membership.save()
    return MembershipRead.model_validate(membership)
```

Add the import for `PermissionDeniedError` if not already present:

```python
from app.core.exceptions import AlreadyExistsError, AppValidationError, ExternalServiceError, NotFoundError, PermissionDeniedError
```

- [ ] **Step 4: Add router endpoints**

Add to `app/organizations/router.py`:

```python
from app.organizations.schemas import MembershipApprove


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
    org_id: str,
    member_id: str,
    user: Annotated[User, Depends(require_active_user)],
) -> MembershipRead:
    # Verify org exists
    org = await Organization.get_or_none(id=org_id)
    if org is None:
        raise NotFoundError("Organization not found")
    return await service.accept_invitation(org_id, member_id, user)
```

- [ ] **Step 5: Run tests**

Run: `task test -- tests/test_organizations.py::TestMembershipApprove tests/test_organizations.py::TestMembershipAccept -v`
Expected: PASS

- [ ] **Step 6: Lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(organizations): membership approve and accept endpoints with tests"
```

---

### Task 9: Membership — Role Change, Remove, and List

**Files:**
- Modify: `app/organizations/service.py`
- Modify: `app/organizations/router.py`
- Modify: `tests/test_organizations.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_organizations.py`:

```python
class TestMembershipRoleChange:
    async def test_change_role(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        user_data, user_token = await create_user(email="invitee@example.com")
        invite_resp = await client.post(
            f"/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        await client.patch(
            f"/organizations/{org_data['id']}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp = await client.patch(
            f"/organizations/{org_data['id']}/members/{member_id}/role",
            json={"role": "viewer"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "viewer"

    async def test_change_role_not_member_status(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        user_data, _ = await create_user(email="invitee@example.com")
        invite_resp = await client.post(
            f"/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        resp = await client.patch(
            f"/organizations/{org_data['id']}/members/{member_id}/role",
            json={"role": "viewer"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400

    async def test_demote_last_admin(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        members_resp = await client.get(
            f"/organizations/{org_data['id']}/members",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        admin_member_id = members_resp.json()[0]["id"]
        resp = await client.patch(
            f"/organizations/{org_data['id']}/members/{admin_member_id}/role",
            json={"role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400


class TestMembershipRemove:
    async def test_admin_removes_member(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        user_data, user_token = await create_user(email="invitee@example.com")
        invite_resp = await client.post(
            f"/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        await client.patch(
            f"/organizations/{org_data['id']}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp = await client.delete(
            f"/organizations/{org_data['id']}/members/{member_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 204

    async def test_self_removal(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        user_data, user_token = await create_user(email="invitee@example.com")
        invite_resp = await client.post(
            f"/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        await client.patch(
            f"/organizations/{org_data['id']}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp = await client.delete(
            f"/organizations/{org_data['id']}/members/{member_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 204

    async def test_last_admin_cannot_leave(
        self,
        client: AsyncClient,
        create_organization: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        members_resp = await client.get(
            f"/organizations/{org_data['id']}/members",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        admin_member_id = members_resp.json()[0]["id"]
        resp = await client.delete(
            f"/organizations/{org_data['id']}/members/{admin_member_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 400

    async def test_non_admin_cannot_remove_others(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        user_data, user_token = await create_user(email="editor@example.com")
        invite_resp = await client.post(
            f"/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        await client.patch(
            f"/organizations/{org_data['id']}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        # Get admin's member ID
        members_resp = await client.get(
            f"/organizations/{org_data['id']}/members",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        admin_member = next(m for m in members_resp.json() if m["role"] == "admin")
        # Editor tries to remove admin
        resp = await client.delete(
            f"/organizations/{org_data['id']}/members/{admin_member['id']}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403


class TestMembershipList:
    async def test_list_members(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, admin_token = await create_organization()
        user_data, user_token = await create_user(email="invitee@example.com")
        invite_resp = await client.post(
            f"/organizations/{org_data['id']}/members/invite",
            json={"user_id": user_data["id"], "role": "editor"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_id = invite_resp.json()["id"]
        await client.patch(
            f"/organizations/{org_data['id']}/members/{member_id}/accept",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        resp = await client.get(
            f"/organizations/{org_data['id']}/members",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_list_members_non_member(
        self,
        client: AsyncClient,
        create_organization: Any,
        create_user: Any,
    ) -> None:
        org_data, _ = await create_organization()
        _, other_token = await create_user(email="outsider@example.com")
        resp = await client.get(
            f"/organizations/{org_data['id']}/members",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `task test -- tests/test_organizations.py::TestMembershipRoleChange tests/test_organizations.py::TestMembershipRemove tests/test_organizations.py::TestMembershipList -v`
Expected: FAIL

- [ ] **Step 3: Implement service functions**

Add to `app/organizations/service.py`:

```python
from app.organizations.schemas import MembershipRoleUpdate


async def _is_last_admin(org_id: str, member_id: str) -> bool:
    admin_count = await Membership.filter(
        organization_id=org_id,
        role=MembershipRole.ADMIN,
        status=MembershipStatus.MEMBER,
    ).count()
    if admin_count > 1:
        return False
    membership = await Membership.get(id=member_id)
    return membership.role == MembershipRole.ADMIN


async def change_member_role(org_id: str, member_id: str, data: MembershipRoleUpdate) -> MembershipRead:
    membership = await Membership.get_or_none(id=member_id, organization_id=org_id)
    if membership is None:
        raise NotFoundError("Membership not found")
    if membership.status != MembershipStatus.MEMBER:
        raise AppValidationError("Can only change role of active members")
    if data.role != MembershipRole.ADMIN and await _is_last_admin(org_id, member_id):
        raise AppValidationError("Cannot remove the last admin")
    membership.role = data.role
    await membership.save()
    return MembershipRead.model_validate(membership)


async def remove_member(org_id: str, member_id: str, user: User) -> None:
    membership = await Membership.get_or_none(id=member_id, organization_id=org_id)
    if membership is None:
        raise NotFoundError("Membership not found")

    is_self = membership.user_id == user.id
    if not is_self:
        caller_membership = await Membership.get_or_none(
            user=user,
            organization_id=org_id,
            status=MembershipStatus.MEMBER,
            role=MembershipRole.ADMIN,
        )
        if caller_membership is None:
            raise PermissionDeniedError("Only admins can remove other members")

    if membership.role == MembershipRole.ADMIN and membership.status == MembershipStatus.MEMBER:
        if await _is_last_admin(org_id, member_id):
            raise AppValidationError("Cannot remove the last admin")

    await membership.delete()


async def list_members(org_id: str) -> list[MembershipRead]:
    members = await Membership.filter(organization_id=org_id)
    return [MembershipRead.model_validate(m) for m in members]
```

- [ ] **Step 4: Add router endpoints**

Add to `app/organizations/router.py`:

```python
from fastapi import Response
from app.organizations.schemas import MembershipRoleUpdate


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
    org_id: str,
    member_id: str,
    user: Annotated[User, Depends(require_active_user)],
) -> Response:
    org = await Organization.get_or_none(id=org_id)
    if org is None:
        raise NotFoundError("Organization not found")
    await service.remove_member(org_id, member_id, user)
    return Response(status_code=204)


@router.get("/organizations/{org_id}/members", response_model=list[MembershipRead])
async def list_members(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_member)],
) -> list[MembershipRead]:
    return await service.list_members(org_id)
```

- [ ] **Step 5: Remove the skip from test_create_org_creator_becomes_admin**

If you added a skip in Task 3, remove it now — the list members endpoint is available.

- [ ] **Step 6: Run all organization tests**

Run: `task test -- tests/test_organizations.py -v`
Expected: ALL PASS

- [ ] **Step 7: Lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(organizations): membership role change, remove, and list endpoints with tests"
```

---

### Task 10: Full Test Suite and Cleanup

**Files:**
- Modify: `tests/test_organizations.py` (if any fixes needed)
- All organization files (lint cleanup)

- [ ] **Step 1: Run the full test suite**

Run: `task test -v`
Expected: ALL tests pass (both users and organizations)

- [ ] **Step 2: Run full CI checks**

Run: `task ci`
Expected: lint + typecheck + test all pass

- [ ] **Step 3: Fix any issues found**

Address any lint, type, or test failures.

- [ ] **Step 4: Final commit (if changes were needed)**

```bash
git add -A
git commit -m "chore(organizations): fix lint and type issues from full CI run"
```

---

## File Summary

| File | Action | Purpose |
|------|--------|---------|
| `app/organizations/models.py` | Modify | Replace contact name fields with `display_name` |
| `app/organizations/schemas.py` | Create | All Pydantic request/response models |
| `app/organizations/service.py` | Create | Business logic for org, contacts, payments, membership |
| `app/organizations/router.py` | Create | All API endpoints |
| `app/organizations/dependencies.py` | Create | Dadata client + org permission dependencies |
| `app/core/exceptions.py` | Modify | Add `ExternalServiceError` (502), change `AppValidationError` to 400 |
| `app/main.py` | Modify | Register organizations router |
| `tests/conftest.py` | Modify | Add Dadata mock, org creation fixtures |
| `tests/test_organizations.py` | Create | All organization tests |
