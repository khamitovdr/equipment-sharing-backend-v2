# Order Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full order lifecycle (creation, offer, confirm, decline, reject, cancel, auto-transitions) following the existing codebase patterns.

**Architecture:** Separate state machine module (pure logic, no ORM) called by async service functions. Dependencies handle auth and resource resolution. Two router groups: user-side (`/orders/`) and org-side (`/organizations/{org_id}/orders/`). Lazy date-based auto-transitions on read.

**Tech Stack:** FastAPI, Tortoise ORM, Pydantic v2, pytest + httpx AsyncClient

**Spec:** `docs/superpowers/specs/2026-03-28-order-lifecycle-design.md`

**IMPORTANT — Python conventions (include in every subagent prompt):**
- No `# type: ignore` — fix the type error or restructure
- No `from __future__ import annotations` — Pydantic v2 and Tortoise need runtime types
- Strict mypy — every function fully typed, no implicit `Any`
- Ruff line length 119, `select = ["ALL"]` with project-specific ignores
- Use `typing.Any` only for Tortoise FK type hints (existing pattern)
- Use `StrEnum` for all enums
- Use `Annotated[Type, Depends(...)]` for FastAPI dependency injection
- Use `create_with_short_id()` for models with 6-char PKs
- Use `ConfigDict(from_attributes=True)` on all read schemas
- Commit messages must NOT mention Claude Code or AI tools

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `app/orders/state_machine.py` | Create | Pure transition logic: OrderAction enum, transition table, `transition()`, `maybe_auto_transition()` |
| `app/orders/schemas.py` | Create | OrderCreate, OrderRead, OrderOffer Pydantic v2 schemas |
| `app/orders/dependencies.py` | Create | `get_order_or_404`, `require_order_requester`, `get_org_order_or_404` |
| `app/orders/service.py` | Create | All order business logic, calls state_machine, listing side effects |
| `app/orders/router.py` | Create | 11 HTTP endpoints (6 user, 5 org) |
| `app/main.py` | Modify | Register orders router |
| `app/core/enums.py` | Modify | Add `OrderAction` enum |
| `tests/test_orders.py` | Create | Integration tests for all endpoints |

---

### Task 1: State Machine

**Files:**
- Modify: `app/core/enums.py`
- Create: `app/orders/state_machine.py`
- Create: `tests/test_order_state_machine.py`

- [ ] **Step 1: Add OrderAction enum to core enums**

In `app/core/enums.py`, add after the `OrderStatus` class:

```python
class OrderAction(StrEnum):
    OFFER = "offer"
    REJECT = "reject"
    CONFIRM = "confirm"
    DECLINE = "decline"
    CANCEL_BY_USER = "cancel_by_user"
    CANCEL_BY_ORG = "cancel_by_org"
    ACTIVATE = "activate"
    FINISH = "finish"
```

- [ ] **Step 2: Write failing tests for state machine**

Create `tests/test_order_state_machine.py`:

```python
from datetime import date, timedelta

import pytest

from app.core.enums import OrderAction, OrderStatus
from app.core.exceptions import AppValidationError
from app.orders.state_machine import maybe_auto_transition, transition


class TestTransition:
    def test_pending_to_offered(self) -> None:
        assert transition(OrderStatus.PENDING, OrderAction.OFFER) == OrderStatus.OFFERED

    def test_pending_to_rejected(self) -> None:
        assert transition(OrderStatus.PENDING, OrderAction.REJECT) == OrderStatus.REJECTED

    def test_offered_to_offered(self) -> None:
        assert transition(OrderStatus.OFFERED, OrderAction.OFFER) == OrderStatus.OFFERED

    def test_offered_to_confirmed(self) -> None:
        assert transition(OrderStatus.OFFERED, OrderAction.CONFIRM) == OrderStatus.CONFIRMED

    def test_offered_to_declined(self) -> None:
        assert transition(OrderStatus.OFFERED, OrderAction.DECLINE) == OrderStatus.DECLINED

    def test_confirmed_to_active(self) -> None:
        assert transition(OrderStatus.CONFIRMED, OrderAction.ACTIVATE) == OrderStatus.ACTIVE

    def test_confirmed_cancel_by_user(self) -> None:
        assert transition(OrderStatus.CONFIRMED, OrderAction.CANCEL_BY_USER) == OrderStatus.CANCELED_BY_USER

    def test_confirmed_cancel_by_org(self) -> None:
        assert transition(OrderStatus.CONFIRMED, OrderAction.CANCEL_BY_ORG) == OrderStatus.CANCELED_BY_ORGANIZATION

    def test_active_to_finished(self) -> None:
        assert transition(OrderStatus.ACTIVE, OrderAction.FINISH) == OrderStatus.FINISHED

    def test_active_cancel_by_user(self) -> None:
        assert transition(OrderStatus.ACTIVE, OrderAction.CANCEL_BY_USER) == OrderStatus.CANCELED_BY_USER

    def test_active_cancel_by_org(self) -> None:
        assert transition(OrderStatus.ACTIVE, OrderAction.CANCEL_BY_ORG) == OrderStatus.CANCELED_BY_ORGANIZATION

    def test_invalid_transition_raises(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.FINISHED, OrderAction.OFFER)

    def test_invalid_transition_from_rejected(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.REJECTED, OrderAction.CONFIRM)

    def test_invalid_transition_from_declined(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.DECLINED, OrderAction.OFFER)

    def test_invalid_transition_pending_confirm(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.PENDING, OrderAction.CONFIRM)


class TestMaybeAutoTransition:
    def test_confirmed_activates_on_start_date(self) -> None:
        today = date(2026, 4, 1)
        result = maybe_auto_transition(
            status=OrderStatus.CONFIRMED,
            offered_start_date=date(2026, 4, 1),
            offered_end_date=date(2026, 4, 10),
            today=today,
        )
        assert result == OrderStatus.ACTIVE

    def test_confirmed_activates_after_start_date(self) -> None:
        today = date(2026, 4, 5)
        result = maybe_auto_transition(
            status=OrderStatus.CONFIRMED,
            offered_start_date=date(2026, 4, 1),
            offered_end_date=date(2026, 4, 10),
            today=today,
        )
        assert result == OrderStatus.ACTIVE

    def test_confirmed_no_transition_before_start(self) -> None:
        today = date(2026, 3, 31)
        result = maybe_auto_transition(
            status=OrderStatus.CONFIRMED,
            offered_start_date=date(2026, 4, 1),
            offered_end_date=date(2026, 4, 10),
            today=today,
        )
        assert result is None

    def test_active_finishes_after_end_date(self) -> None:
        today = date(2026, 4, 11)
        result = maybe_auto_transition(
            status=OrderStatus.ACTIVE,
            offered_start_date=date(2026, 4, 1),
            offered_end_date=date(2026, 4, 10),
            today=today,
        )
        assert result == OrderStatus.FINISHED

    def test_active_no_transition_on_end_date(self) -> None:
        today = date(2026, 4, 10)
        result = maybe_auto_transition(
            status=OrderStatus.ACTIVE,
            offered_start_date=date(2026, 4, 1),
            offered_end_date=date(2026, 4, 10),
            today=today,
        )
        assert result is None

    def test_chained_confirmed_to_finished(self) -> None:
        today = date(2026, 4, 15)
        result = maybe_auto_transition(
            status=OrderStatus.CONFIRMED,
            offered_start_date=date(2026, 4, 1),
            offered_end_date=date(2026, 4, 10),
            today=today,
        )
        assert result == OrderStatus.FINISHED

    def test_pending_no_transition(self) -> None:
        today = date(2026, 4, 5)
        result = maybe_auto_transition(
            status=OrderStatus.PENDING,
            offered_start_date=None,
            offered_end_date=None,
            today=today,
        )
        assert result is None

    def test_offered_no_transition(self) -> None:
        today = date(2026, 4, 5)
        result = maybe_auto_transition(
            status=OrderStatus.OFFERED,
            offered_start_date=date(2026, 4, 1),
            offered_end_date=date(2026, 4, 10),
            today=today,
        )
        assert result is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_order_state_machine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.orders.state_machine'`

- [ ] **Step 4: Implement state machine**

Create `app/orders/state_machine.py`:

```python
from __future__ import annotations

from datetime import date

from app.core.enums import OrderAction, OrderStatus
from app.core.exceptions import AppValidationError

_TRANSITIONS: dict[tuple[OrderStatus, OrderAction], OrderStatus] = {
    (OrderStatus.PENDING, OrderAction.OFFER): OrderStatus.OFFERED,
    (OrderStatus.PENDING, OrderAction.REJECT): OrderStatus.REJECTED,
    (OrderStatus.OFFERED, OrderAction.OFFER): OrderStatus.OFFERED,
    (OrderStatus.OFFERED, OrderAction.CONFIRM): OrderStatus.CONFIRMED,
    (OrderStatus.OFFERED, OrderAction.DECLINE): OrderStatus.DECLINED,
    (OrderStatus.CONFIRMED, OrderAction.ACTIVATE): OrderStatus.ACTIVE,
    (OrderStatus.CONFIRMED, OrderAction.CANCEL_BY_USER): OrderStatus.CANCELED_BY_USER,
    (OrderStatus.CONFIRMED, OrderAction.CANCEL_BY_ORG): OrderStatus.CANCELED_BY_ORGANIZATION,
    (OrderStatus.ACTIVE, OrderAction.FINISH): OrderStatus.FINISHED,
    (OrderStatus.ACTIVE, OrderAction.CANCEL_BY_USER): OrderStatus.CANCELED_BY_USER,
    (OrderStatus.ACTIVE, OrderAction.CANCEL_BY_ORG): OrderStatus.CANCELED_BY_ORGANIZATION,
}


def transition(current: OrderStatus, action: OrderAction) -> OrderStatus:
    key = (current, action)
    if key not in _TRANSITIONS:
        msg = f"Cannot {action.value} order in status {current.value}"
        raise AppValidationError(msg)
    return _TRANSITIONS[key]


# TODO: Replace with Temporal workflow for automatic order status transitions
def maybe_auto_transition(
    *,
    status: OrderStatus,
    offered_start_date: date | None,
    offered_end_date: date | None,
    today: date,
) -> OrderStatus | None:
    current = status

    if current == OrderStatus.CONFIRMED and offered_start_date is not None and today >= offered_start_date:
        current = OrderStatus.ACTIVE

    if current == OrderStatus.ACTIVE and offered_end_date is not None and today > offered_end_date:
        current = OrderStatus.FINISHED

    if current == status:
        return None
    return current
```

**Note:** This file uses `from __future__ import annotations` because it has no Pydantic models or Tortoise fields — it's pure logic. This is the one exception to the project convention.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_order_state_machine.py -v`
Expected: All 16 tests PASS

- [ ] **Step 6: Run lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add app/core/enums.py app/orders/state_machine.py tests/test_order_state_machine.py
git commit -m "feat(orders): add order state machine with transition logic"
```

---

### Task 2: Schemas

**Files:**
- Create: `app/orders/schemas.py`

- [ ] **Step 1: Create order schemas**

Create `app/orders/schemas.py`:

```python
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from typing_extensions import Self

from app.core.enums import OrderStatus


class OrderCreate(BaseModel):
    listing_id: str
    requested_start_date: date
    requested_end_date: date

    @model_validator(mode="after")
    def start_before_end(self) -> Self:
        if self.requested_start_date > self.requested_end_date:
            msg = "requested_start_date must be <= requested_end_date"
            raise ValueError(msg)
        return self


class OrderOffer(BaseModel):
    offered_cost: Decimal
    offered_start_date: date
    offered_end_date: date

    @field_validator("offered_cost")
    @classmethod
    def positive_cost(cls, v: Decimal) -> Decimal:
        if v <= 0:
            msg = "offered_cost must be positive"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def start_before_end(self) -> Self:
        if self.offered_start_date > self.offered_end_date:
            msg = "offered_start_date must be <= offered_end_date"
            raise ValueError(msg)
        return self


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    listing_id: str
    organization_id: str
    requester_id: str
    requested_start_date: date
    requested_end_date: date
    status: OrderStatus
    estimated_cost: Decimal | None
    offered_cost: Decimal | None
    offered_start_date: date | None
    offered_end_date: date | None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 2: Run lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add app/orders/schemas.py
git commit -m "feat(orders): add order Pydantic schemas"
```

---

### Task 3: Dependencies

**Files:**
- Create: `app/orders/dependencies.py`

- [ ] **Step 1: Create order dependencies**

Create `app/orders/dependencies.py`:

```python
from fastapi import Depends, Path
from typing_extensions import Annotated

from app.core.dependencies import require_active_user
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.orders.models import Order
from app.users.models import User


async def get_order_or_404(order_id: str = Path()) -> Order:
    order = await Order.get_or_none(id=order_id)
    if order is None:
        raise NotFoundError("Order not found")
    return order


async def require_order_requester(
    order: Annotated[Order, Depends(get_order_or_404)],
    user: Annotated[User, Depends(require_active_user)],
) -> Order:
    if order.requester_id != user.id:
        raise PermissionDeniedError("You are not the requester of this order")
    return order


async def get_org_order_or_404(org_id: str = Path(), order_id: str = Path()) -> Order:
    order = await Order.get_or_none(id=order_id, organization_id=org_id)
    if order is None:
        raise NotFoundError("Order not found")
    return order
```

- [ ] **Step 2: Run lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add app/orders/dependencies.py
git commit -m "feat(orders): add order dependency injection helpers"
```

---

### Task 4: Service Layer

**Files:**
- Create: `app/orders/service.py`

- [ ] **Step 1: Create the service module**

Create `app/orders/service.py`:

```python
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.core.enums import ListingStatus, OrderAction, OrderStatus, OrganizationStatus
from app.core.exceptions import AppValidationError, NotFoundError, PermissionDeniedError
from app.core.identifiers import create_with_short_id
from app.listings.models import Listing
from app.orders.models import Order
from app.orders.schemas import OrderCreate, OrderOffer, OrderRead
from app.orders.state_machine import maybe_auto_transition, transition
from app.users.models import User


async def _apply_auto_transition(order: Order) -> Order:
    # TODO: Replace with Temporal workflow for automatic order status transitions
    new_status = maybe_auto_transition(
        status=order.status,
        offered_start_date=order.offered_start_date,
        offered_end_date=order.offered_end_date,
        today=date.today(),
    )
    if new_status is None:
        return order

    order.status = new_status
    await order.save()

    await order.fetch_related("listing")
    listing: Listing = order.listing

    if new_status == OrderStatus.ACTIVE:
        listing.status = ListingStatus.IN_RENT
        await listing.save()
    elif new_status == OrderStatus.FINISHED:
        listing.status = ListingStatus.PUBLISHED
        await listing.save()

    return order


async def _to_read(order: Order) -> OrderRead:
    order = await _apply_auto_transition(order)
    return OrderRead.model_validate(order)


async def create_order(user: User, data: OrderCreate) -> OrderRead:
    listing = await Listing.get_or_none(id=data.listing_id).select_related("organization")
    if listing is None:
        raise NotFoundError("Listing not found")

    if listing.status != ListingStatus.PUBLISHED:
        raise AppValidationError("Listing is not available for ordering")

    if listing.organization.status != OrganizationStatus.VERIFIED:
        raise PermissionDeniedError("Organization is not verified")

    if data.requested_start_date < date.today():
        raise AppValidationError("requested_start_date cannot be in the past")

    days = Decimal((data.requested_end_date - data.requested_start_date).days + 1)
    estimated_cost = (listing.price * days).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    order = await create_with_short_id(
        Order,
        listing=listing,
        organization=listing.organization,
        requester=user,
        requested_start_date=data.requested_start_date,
        requested_end_date=data.requested_end_date,
        estimated_cost=estimated_cost,
    )
    return OrderRead.model_validate(order)


async def offer_order(order: Order, data: OrderOffer) -> OrderRead:
    new_status = transition(order.status, OrderAction.OFFER)
    order.status = new_status
    order.offered_cost = data.offered_cost
    order.offered_start_date = data.offered_start_date
    order.offered_end_date = data.offered_end_date
    await order.save()
    return OrderRead.model_validate(order)


async def reject_order(order: Order) -> OrderRead:
    order.status = transition(order.status, OrderAction.REJECT)
    await order.save()
    return OrderRead.model_validate(order)


async def confirm_order(order: Order) -> OrderRead:
    order.status = transition(order.status, OrderAction.CONFIRM)
    await order.save()
    return await _to_read(order)


async def decline_order(order: Order) -> OrderRead:
    order.status = transition(order.status, OrderAction.DECLINE)
    await order.save()
    return OrderRead.model_validate(order)


async def _cancel_order(order: Order, action: OrderAction) -> OrderRead:
    order.status = transition(order.status, action)
    await order.save()

    await order.fetch_related("listing")
    listing: Listing = order.listing
    if listing.status == ListingStatus.IN_RENT:
        listing.status = ListingStatus.PUBLISHED
        await listing.save()

    return OrderRead.model_validate(order)


async def cancel_order_by_user(order: Order) -> OrderRead:
    return await _cancel_order(order, OrderAction.CANCEL_BY_USER)


async def cancel_order_by_org(order: Order) -> OrderRead:
    return await _cancel_order(order, OrderAction.CANCEL_BY_ORG)


async def get_order(order: Order) -> OrderRead:
    return await _to_read(order)


async def list_user_orders(user: User) -> list[OrderRead]:
    orders = await Order.filter(requester=user).order_by("-updated_at")
    return [await _to_read(order) for order in orders]


async def list_org_orders(org_id: str) -> list[OrderRead]:
    orders = await Order.filter(organization_id=org_id).order_by("-updated_at")
    return [await _to_read(order) for order in orders]
```

- [ ] **Step 2: Run lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add app/orders/service.py
git commit -m "feat(orders): add order service layer with business logic"
```

---

### Task 5: Router & App Registration

**Files:**
- Create: `app/orders/router.py`
- Modify: `app/main.py`

- [ ] **Step 1: Create the router**

Create `app/orders/router.py`:

```python
from fastapi import APIRouter, Depends, status
from typing_extensions import Annotated

from app.core.dependencies import require_active_user
from app.orders import service
from app.orders.dependencies import get_org_order_or_404, require_order_requester
from app.orders.models import Order
from app.orders.schemas import OrderCreate, OrderOffer, OrderRead
from app.organizations.dependencies import require_org_editor
from app.organizations.models import Membership
from app.users.models import User

router = APIRouter()


# --- User (renter) endpoints ---


@router.post("/orders/", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def create_order(
    data: OrderCreate,
    user: Annotated[User, Depends(require_active_user)],
) -> OrderRead:
    return await service.create_order(user, data)


@router.get("/orders/", response_model=list[OrderRead])
async def list_my_orders(
    user: Annotated[User, Depends(require_active_user)],
) -> list[OrderRead]:
    return await service.list_user_orders(user)


@router.get("/orders/{order_id}", response_model=OrderRead)
async def get_my_order(
    order: Annotated[Order, Depends(require_order_requester)],
) -> OrderRead:
    return await service.get_order(order)


@router.patch("/orders/{order_id}/confirm", response_model=OrderRead)
async def confirm_order(
    order: Annotated[Order, Depends(require_order_requester)],
) -> OrderRead:
    return await service.confirm_order(order)


@router.patch("/orders/{order_id}/decline", response_model=OrderRead)
async def decline_order(
    order: Annotated[Order, Depends(require_order_requester)],
) -> OrderRead:
    return await service.decline_order(order)


@router.patch("/orders/{order_id}/cancel", response_model=OrderRead)
async def cancel_order_by_user(
    order: Annotated[Order, Depends(require_order_requester)],
) -> OrderRead:
    return await service.cancel_order_by_user(order)


# --- Organization (owner) endpoints ---


@router.get("/organizations/{org_id}/orders/", response_model=list[OrderRead])
async def list_org_orders(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_editor)],
) -> list[OrderRead]:
    return await service.list_org_orders(org_id)


@router.get("/organizations/{org_id}/orders/{order_id}", response_model=OrderRead)
async def get_org_order(
    order: Annotated[Order, Depends(get_org_order_or_404)],
    _membership: Annotated[Membership, Depends(require_org_editor)],
) -> OrderRead:
    return await service.get_order(order)


@router.patch("/organizations/{org_id}/orders/{order_id}/offer", response_model=OrderRead)
async def offer_order(
    order: Annotated[Order, Depends(get_org_order_or_404)],
    data: OrderOffer,
    _membership: Annotated[Membership, Depends(require_org_editor)],
) -> OrderRead:
    return await service.offer_order(order, data)


@router.patch("/organizations/{org_id}/orders/{order_id}/reject", response_model=OrderRead)
async def reject_order(
    order: Annotated[Order, Depends(get_org_order_or_404)],
    _membership: Annotated[Membership, Depends(require_org_editor)],
) -> OrderRead:
    return await service.reject_order(order)


@router.patch("/organizations/{org_id}/orders/{order_id}/cancel", response_model=OrderRead)
async def cancel_order_by_org(
    order: Annotated[Order, Depends(get_org_order_or_404)],
    _membership: Annotated[Membership, Depends(require_org_editor)],
) -> OrderRead:
    return await service.cancel_order_by_org(order)
```

- [ ] **Step 2: Register router in main.py**

In `app/main.py`, add the import alongside the other router imports:

```python
from app.orders.router import router as orders_router
```

And add this line after the existing `include_router` calls:

```python
application.include_router(orders_router)
```

- [ ] **Step 3: Run lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add app/orders/router.py app/main.py
git commit -m "feat(orders): add order router and register in app"
```

---

### Task 6: Test Fixtures

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Add order test fixtures**

In `tests/conftest.py`, add these fixtures after the existing `verified_org` fixture. These build on existing fixtures (`create_user`, `verified_org`, `create_organization`, `seed_categories`):

```python
@pytest.fixture
async def create_listing(client: AsyncClient, verified_org: tuple[dict[str, Any], str], seed_categories: list[str]) -> AsyncGenerator[tuple[str, str, str], None]:
    """Creates a published listing in a verified org. Returns (listing_id, org_id, org_admin_token)."""
    org_data, org_token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0]

    resp = await client.post(
        f"/organizations/{org_id}/listings/",
        json={
            "name": "Excavator CAT 320",
            "category_id": category_id,
            "price": 5000.00,
            "description": "Heavy excavator for rent",
        },
        headers={"Authorization": f"Bearer {org_token}"},
    )
    listing_id = resp.json()["id"]

    await client.patch(
        f"/organizations/{org_id}/listings/{listing_id}/status",
        json={"status": "published"},
        headers={"Authorization": f"Bearer {org_token}"},
    )

    yield listing_id, org_id, org_token


@pytest.fixture
async def renter_token(create_user: Any) -> str:
    """Creates a separate user to act as the renter. Returns their token."""
    _, token = await create_user(
        email="renter@example.com",
        phone="+79001112233",
        name="Renter",
        surname="Testov",
    )
    return token
```

- [ ] **Step 2: Run lint**

Run: `task lint:fix`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test(orders): add order test fixtures"
```

---

### Task 7: Integration Tests — Order Creation

**Files:**
- Create: `tests/test_orders.py`

- [ ] **Step 1: Write order creation tests**

Create `tests/test_orders.py`:

```python
from datetime import date, timedelta
from typing import Any

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
class TestCreateOrder:
    async def test_create_order_success(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        start = date.today() + timedelta(days=1)
        end = start + timedelta(days=4)

        resp = await client.post(
            "/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "pending"
        assert body["listing_id"] == listing_id
        assert body["estimated_cost"] is not None

    async def test_create_order_listing_not_found(
        self,
        client: AsyncClient,
        renter_token: str,
    ) -> None:
        start = date.today() + timedelta(days=1)
        end = start + timedelta(days=4)

        resp = await client.post(
            "/orders/",
            json={
                "listing_id": "NOTEXIST",
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 404

    async def test_create_order_listing_not_published(
        self,
        client: AsyncClient,
        verified_org: tuple[dict[str, Any], str],
        seed_categories: list[str],
        renter_token: str,
    ) -> None:
        org_data, org_token = verified_org
        org_id = org_data["id"]

        resp = await client.post(
            f"/organizations/{org_id}/listings/",
            json={
                "name": "Hidden item",
                "category_id": seed_categories[0],
                "price": 1000.00,
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )
        listing_id = resp.json()["id"]

        start = date.today() + timedelta(days=1)
        end = start + timedelta(days=2)
        resp = await client.post(
            "/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 400

    async def test_create_order_unverified_org(
        self,
        client: AsyncClient,
        create_organization: Any,
        seed_categories: list[str],
        renter_token: str,
    ) -> None:
        org_data, org_token = await create_organization()
        org_id = org_data["id"]

        resp = await client.post(
            f"/organizations/{org_id}/listings/",
            json={
                "name": "Unverified item",
                "category_id": seed_categories[0],
                "price": 1000.00,
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )
        listing_id = resp.json()["id"]

        await client.patch(
            f"/organizations/{org_id}/listings/{listing_id}/status",
            json={"status": "published"},
            headers={"Authorization": f"Bearer {org_token}"},
        )

        start = date.today() + timedelta(days=1)
        end = start + timedelta(days=2)
        resp = await client.post(
            "/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 403

    async def test_create_order_start_in_past(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing

        resp = await client.post(
            "/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": (date.today() - timedelta(days=1)).isoformat(),
                "requested_end_date": date.today().isoformat(),
            },
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 400

    async def test_create_order_start_after_end(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        start = date.today() + timedelta(days=5)
        end = date.today() + timedelta(days=1)

        resp = await client.post(
            "/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 422

    async def test_create_order_estimated_cost_calculation(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        start = date.today() + timedelta(days=1)
        end = start + timedelta(days=4)

        resp = await client.post(
            "/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        body = resp.json()
        assert body["estimated_cost"] == "25000.00"

    async def test_create_order_unauthenticated(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        start = date.today() + timedelta(days=1)
        end = start + timedelta(days=2)

        resp = await client.post(
            "/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
            },
        )
        assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_orders.py::TestCreateOrder -v`
Expected: All 8 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_orders.py
git commit -m "test(orders): add order creation integration tests"
```

---

### Task 8: Integration Tests — Org Actions (Offer, Reject)

**Files:**
- Modify: `tests/test_orders.py`

- [ ] **Step 1: Add a helper fixture and org action tests**

Add at the top of `tests/test_orders.py` (after imports), a helper to create an order:

```python
async def _create_order(
    client: AsyncClient,
    listing_id: str,
    token: str,
    start_offset: int = 1,
    duration: int = 4,
) -> dict[str, Any]:
    start = date.today() + timedelta(days=start_offset)
    end = start + timedelta(days=duration)
    resp = await client.post(
        "/orders/",
        json={
            "listing_id": listing_id,
            "requested_start_date": start.isoformat(),
            "requested_end_date": end.isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    return resp.json()
```

Then add these test classes:

```python
@pytest.mark.anyio
class TestOfferOrder:
    async def test_offer_success(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        start = date.today() + timedelta(days=2)
        end = start + timedelta(days=5)
        resp = await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/offer",
            json={
                "offered_cost": "30000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "offered"
        assert body["offered_cost"] == "30000.00"

    async def test_re_offer_updates_terms(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        start = date.today() + timedelta(days=2)
        end = start + timedelta(days=5)
        await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/offer",
            json={
                "offered_cost": "30000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )

        resp = await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/offer",
            json={
                "offered_cost": "25000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["offered_cost"] == "25000.00"
        assert resp.json()["status"] == "offered"

    async def test_offer_wrong_org(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        create_organization: Any,
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        other_org_data, other_token = await create_organization()
        other_org_id = other_org_data["id"]

        start = date.today() + timedelta(days=2)
        end = start + timedelta(days=5)
        resp = await client.patch(
            f"/organizations/{other_org_id}/orders/{order['id']}/offer",
            json={
                "offered_cost": "30000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 404

    async def test_offer_invalid_status(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        start = date.today() + timedelta(days=2)
        end = start + timedelta(days=5)
        offer_data = {
            "offered_cost": "30000.00",
            "offered_start_date": start.isoformat(),
            "offered_end_date": end.isoformat(),
        }

        await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/offer",
            json=offer_data,
            headers={"Authorization": f"Bearer {org_token}"},
        )
        await client.patch(
            f"/orders/{order['id']}/confirm",
            headers={"Authorization": f"Bearer {renter_token}"},
        )

        resp = await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/offer",
            json=offer_data,
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 400


@pytest.mark.anyio
class TestRejectOrder:
    async def test_reject_success(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        resp = await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/reject",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    async def test_reject_non_pending(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        start = date.today() + timedelta(days=2)
        end = start + timedelta(days=5)
        await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/offer",
            json={
                "offered_cost": "30000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )

        resp = await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/reject",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 400
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_orders.py::TestOfferOrder tests/test_orders.py::TestRejectOrder -v`
Expected: All 6 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_orders.py
git commit -m "test(orders): add offer and reject integration tests"
```

---

### Task 9: Integration Tests — User Actions (Confirm, Decline, Cancel)

**Files:**
- Modify: `tests/test_orders.py`

- [ ] **Step 1: Add a helper to create an offered order and user action tests**

Add another helper after `_create_order`:

```python
async def _create_offered_order(
    client: AsyncClient,
    listing_id: str,
    org_id: str,
    org_token: str,
    renter_token: str,
) -> dict[str, Any]:
    order = await _create_order(client, listing_id, renter_token)
    start = date.today() + timedelta(days=2)
    end = start + timedelta(days=5)
    resp = await client.patch(
        f"/organizations/{org_id}/orders/{order['id']}/offer",
        json={
            "offered_cost": "30000.00",
            "offered_start_date": start.isoformat(),
            "offered_end_date": end.isoformat(),
        },
        headers={"Authorization": f"Bearer {org_token}"},
    )
    assert resp.status_code == 200
    return resp.json()
```

Then add test classes:

```python
@pytest.mark.anyio
class TestConfirmOrder:
    async def test_confirm_success(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        resp = await client.patch(
            f"/orders/{order['id']}/confirm",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"

    async def test_confirm_not_requester(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        create_user: Any,
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        _, other_token = await create_user(
            email="other@example.com",
            phone="+79009998877",
            name="Other",
            surname="User",
        )
        resp = await client.patch(
            f"/orders/{order['id']}/confirm",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403

    async def test_confirm_non_offered(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        resp = await client.patch(
            f"/orders/{order['id']}/confirm",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 400


@pytest.mark.anyio
class TestDeclineOrder:
    async def test_decline_success(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        resp = await client.patch(
            f"/orders/{order['id']}/decline",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "declined"


@pytest.mark.anyio
class TestCancelOrder:
    async def test_user_cancel_confirmed(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        await client.patch(
            f"/orders/{order['id']}/confirm",
            headers={"Authorization": f"Bearer {renter_token}"},
        )

        resp = await client.patch(
            f"/orders/{order['id']}/cancel",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_user"

    async def test_org_cancel_confirmed(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        await client.patch(
            f"/orders/{order['id']}/confirm",
            headers={"Authorization": f"Bearer {renter_token}"},
        )

        resp = await client.patch(
            f"/organizations/{org_id}/orders/{order['id']}/cancel",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_organization"

    async def test_cancel_pending_fails(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        resp = await client.patch(
            f"/orders/{order['id']}/cancel",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 400
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_orders.py::TestConfirmOrder tests/test_orders.py::TestDeclineOrder tests/test_orders.py::TestCancelOrder -v`
Expected: All 7 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_orders.py
git commit -m "test(orders): add confirm, decline, and cancel integration tests"
```

---

### Task 10: Integration Tests — List & Get Orders

**Files:**
- Modify: `tests/test_orders.py`

- [ ] **Step 1: Add list and get tests**

```python
@pytest.mark.anyio
class TestListOrders:
    async def test_list_user_orders(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        await _create_order(client, listing_id, renter_token)
        await _create_order(client, listing_id, renter_token, start_offset=10)

        resp = await client.get(
            "/orders/",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_list_user_orders_empty(
        self,
        client: AsyncClient,
        renter_token: str,
    ) -> None:
        resp = await client.get(
            "/orders/",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_org_orders(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        await _create_order(client, listing_id, renter_token)

        resp = await client.get(
            f"/organizations/{org_id}/orders/",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_list_org_orders_unauthorized(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        _listing_id, org_id, _org_token = create_listing

        resp = await client.get(
            f"/organizations/{org_id}/orders/",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 403


@pytest.mark.anyio
class TestGetOrder:
    async def test_get_user_order(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        resp = await client.get(
            f"/orders/{order['id']}",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == order["id"]

    async def test_get_org_order(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        resp = await client.get(
            f"/organizations/{org_id}/orders/{order['id']}",
            headers={"Authorization": f"Bearer {org_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == order["id"]

    async def test_get_order_not_requester(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        create_user: Any,
        renter_token: str,
    ) -> None:
        listing_id, _org_id, _org_token = create_listing
        order = await _create_order(client, listing_id, renter_token)

        _, other_token = await create_user(
            email="stranger@example.com",
            phone="+79005554433",
            name="Stranger",
            surname="Person",
        )
        resp = await client.get(
            f"/orders/{order['id']}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_orders.py::TestListOrders tests/test_orders.py::TestGetOrder -v`
Expected: All 7 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_orders.py
git commit -m "test(orders): add list and get order integration tests"
```

---

### Task 11: Integration Tests — Listing Side Effects

**Files:**
- Modify: `tests/test_orders.py`

- [ ] **Step 1: Add listing side effect tests**

```python
@pytest.mark.anyio
class TestListingSideEffects:
    async def test_cancel_active_restores_listing_to_published(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing

        start = date.today()
        end = start + timedelta(days=5)
        resp = await client.post(
            "/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 201
        order_id = resp.json()["id"]

        await client.patch(
            f"/organizations/{org_id}/orders/{order_id}/offer",
            json={
                "offered_cost": "25000.00",
                "offered_start_date": start.isoformat(),
                "offered_end_date": end.isoformat(),
            },
            headers={"Authorization": f"Bearer {org_token}"},
        )

        await client.patch(
            f"/orders/{order_id}/confirm",
            headers={"Authorization": f"Bearer {renter_token}"},
        )

        # Fetch the order — lazy eval should transition to active since start is today
        resp = await client.get(
            f"/orders/{order_id}",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.json()["status"] == "active"

        # Check listing is in_rent
        resp = await client.get(f"/listings/{listing_id}")
        assert resp.json()["status"] == "in_rent"

        # Cancel the order
        resp = await client.patch(
            f"/orders/{order_id}/cancel",
            headers={"Authorization": f"Bearer {renter_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "canceled_by_user"

        # Check listing is published again
        resp = await client.get(f"/listings/{listing_id}")
        assert resp.json()["status"] == "published"

    async def test_cancel_confirmed_does_not_change_listing(
        self,
        client: AsyncClient,
        create_listing: tuple[str, str, str],
        renter_token: str,
    ) -> None:
        listing_id, org_id, org_token = create_listing
        order = await _create_offered_order(client, listing_id, org_id, org_token, renter_token)

        await client.patch(
            f"/orders/{order['id']}/confirm",
            headers={"Authorization": f"Bearer {renter_token}"},
        )

        resp = await client.get(f"/listings/{listing_id}")
        assert resp.json()["status"] == "published"

        await client.patch(
            f"/orders/{order['id']}/cancel",
            headers={"Authorization": f"Bearer {renter_token}"},
        )

        resp = await client.get(f"/listings/{listing_id}")
        assert resp.json()["status"] == "published"
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_orders.py::TestListingSideEffects -v`
Expected: All 2 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_orders.py
git commit -m "test(orders): add listing side effect integration tests"
```

---

### Task 12: Final Verification

- [ ] **Step 1: Run the full test suite**

Run: `task test`
Expected: All tests pass (existing + new)

- [ ] **Step 2: Run lint and typecheck**

Run: `task lint:fix && task typecheck`
Expected: No errors

- [ ] **Step 3: Run CI locally**

Run: `task ci`
Expected: lint + typecheck + test all pass

- [ ] **Step 4: Final commit if any lint fixes**

```bash
git add -u
git commit -m "chore: fix lint issues from order lifecycle implementation"
```
