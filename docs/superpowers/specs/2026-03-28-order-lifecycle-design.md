# Order Lifecycle — Design Spec

Implements section 5 of `docs/business-logic.md`: the full order lifecycle from creation through rental completion or cancellation.

---

## Module Structure

```
app/orders/
├── __init__.py          # existing
├── models.py            # existing (Order model already defined)
├── state_machine.py     # NEW — pure transition logic
├── schemas.py           # NEW — Pydantic v2 request/response
├── service.py           # NEW — business logic, calls state_machine
├── dependencies.py      # NEW — order-level permission helpers
└── router.py            # NEW — HTTP endpoints
```

Plus: register the orders router in `app/main.py`.

---

## State Machine (`state_machine.py`)

A pure module with no ORM or framework dependencies.

### OrderAction Enum

```
OFFER, REJECT, CONFIRM, DECLINE, CANCEL_BY_USER, CANCEL_BY_ORG, ACTIVATE, FINISH
```

`ACTIVATE` and `FINISH` are internal actions triggered by lazy date evaluation, not by user/org HTTP requests.

### Transition Table

| Current Status | Action | New Status |
|---------------|--------|------------|
| pending | OFFER | offered |
| pending | REJECT | rejected |
| offered | OFFER | offered |
| offered | CONFIRM | confirmed |
| offered | DECLINE | declined |
| confirmed | ACTIVATE | active |
| confirmed | CANCEL_BY_USER | canceled_by_user |
| confirmed | CANCEL_BY_ORG | canceled_by_organization |
| active | FINISH | finished |
| active | CANCEL_BY_USER | canceled_by_user |
| active | CANCEL_BY_ORG | canceled_by_organization |

Terminal statuses (no outgoing transitions): `finished`, `rejected`, `declined`, `canceled_by_user`, `canceled_by_organization`.

### Functions

**`transition(current_status: OrderStatus, action: OrderAction) -> OrderStatus`**

Pure function. Looks up `(current_status, action)` in the transition table. Returns the new status or raises `AppValidationError` with a message describing the invalid transition.

**`maybe_auto_transition(status, offered_start_date, offered_end_date, today) -> OrderStatus | None`**

Checks date-based automatic transitions. Applies transitions in sequence to handle the case where both start and end dates have passed (confirmed → active → finished):
- If `status == confirmed` and `today >= offered_start_date` → transition to `active`, then continue checking
- If `status == active` and `today > offered_end_date` → transition to `finished`
- Returns the final status if any transition occurred, or `None` if no transition applies

This function gets a `# TODO: Replace with Temporal workflow` comment.

---

## Schemas (`schemas.py`)

### OrderCreate

| Field | Type | Validation |
|-------|------|------------|
| listing_id | str | required |
| requested_start_date | date | required, not in past, <= requested_end_date |
| requested_end_date | date | required |

Schema-level validator: `requested_start_date <= requested_end_date`.

Note: "not in past" is validated in the service layer (needs `date.today()` which is environment-dependent).

### OrderRead

`ConfigDict(from_attributes=True)`

| Field | Type |
|-------|------|
| id | str |
| listing_id | str |
| organization_id | str |
| requester_id | str |
| requested_start_date | date |
| requested_end_date | date |
| status | OrderStatus |
| estimated_cost | Decimal | None |
| offered_cost | Decimal | None |
| offered_start_date | date | None |
| offered_end_date | date | None |
| created_at | datetime |
| updated_at | datetime |

### OrderOffer

| Field | Type | Validation |
|-------|------|------------|
| offered_cost | Decimal | required, positive |
| offered_start_date | date | required |
| offered_end_date | date | required, >= offered_start_date |

---

## Dependencies (`dependencies.py`)

### `get_order_or_404(order_id: str) -> Order`

Fetches order by ID. Raises `NotFoundError` if not found.

### `require_order_requester(order, user) -> Order`

Composes `get_order_or_404` + `require_active_user`. Verifies `order.requester_id == user.id`. Raises `PermissionDeniedError` if not. Returns the `Order`.

### `get_org_order_or_404(org_id: str, order_id: str) -> Order`

Fetches order scoped to organization: `id=order_id, organization_id=org_id`. Raises `NotFoundError` if not found. Used with the existing `require_org_editor` dependency in routers.

---

## Service (`service.py`)

All functions are async. Service receives pre-validated `Order` objects from dependencies where applicable.

### `create_order(user: User, data: OrderCreate) -> OrderRead`

**Preconditions:**
1. Listing exists → `NotFoundError`
2. Listing status is `published` → `AppValidationError`
3. Listing's organization is `verified` → `PermissionDeniedError`
4. `requested_start_date` not in past → `AppValidationError`

**Logic:**
- Calculate `estimated_cost = listing.price * ((requested_end_date - requested_start_date).days + 1)`, rounded to 2 decimal places
- Create order via `create_with_short_id(Order, ...)`
- Set `organization` from listing's organization

### `offer_order(order: Order, data: OrderOffer) -> OrderRead`

Calls `state_machine.transition(order.status, OFFER)`. Sets `offered_cost`, `offered_start_date`, `offered_end_date`. Saves.

### `reject_order(order: Order) -> OrderRead`

Calls `state_machine.transition(order.status, REJECT)`. Saves.

### `confirm_order(order: Order) -> OrderRead`

Calls `state_machine.transition(order.status, CONFIRM)`. Saves.

### `decline_order(order: Order) -> OrderRead`

Calls `state_machine.transition(order.status, DECLINE)`. Saves.

### `cancel_order_by_user(order: Order) -> OrderRead`

Calls `state_machine.transition(order.status, CANCEL_BY_USER)`. If listing was `in_rent`, restores to `published`. Saves.

### `cancel_order_by_org(order: Order) -> OrderRead`

Calls `state_machine.transition(order.status, CANCEL_BY_ORG)`. If listing was `in_rent`, restores to `published`. Saves.

### `get_order(order: Order) -> OrderRead`

Applies `maybe_auto_transition()`. If transition fires, updates order status (and listing status for activate/finish). Returns `OrderRead`.

### `list_user_orders(user: User) -> list[OrderRead]`

Fetches all orders where `requester=user`, applies lazy auto-transitions, returns list.

### `list_org_orders(org_id: str) -> list[OrderRead]`

Fetches all orders where `organization_id=org_id`, applies lazy auto-transitions, returns list.

### Lazy Auto-Transition Logic

Private helper `_apply_auto_transitions(order: Order) -> Order`:
- Calls `maybe_auto_transition(order.status, order.offered_start_date, order.offered_end_date, date.today())`
- If result is `active`: set `order.status = active`, set `listing.status = in_rent`, save both
- If result is `finished`: set `order.status = finished`, set `listing.status = published`, save both (handles chained confirmed → active → finished when both dates have passed)
- If `None`: no-op

---

## Listing Side Effects

| Order Transition | Listing Side Effect |
|-----------------|---------------------|
| confirmed → active (lazy) | listing.status = `in_rent` |
| active → finished (lazy) | listing.status = `published` |
| cancel from active | listing.status = `published` |
| cancel from confirmed | no change |

Applied in service layer. State machine stays pure.

---

## Router (`router.py`)

### User (renter) endpoints

| Method | Path | Dependency | Service |
|--------|------|------------|---------|
| POST | `/orders/` | `require_active_user` | `create_order` |
| GET | `/orders/` | `require_active_user` | `list_user_orders` |
| GET | `/orders/{order_id}` | `require_order_requester` | `get_order` |
| PATCH | `/orders/{order_id}/confirm` | `require_order_requester` | `confirm_order` |
| PATCH | `/orders/{order_id}/decline` | `require_order_requester` | `decline_order` |
| PATCH | `/orders/{order_id}/cancel` | `require_order_requester` | `cancel_order_by_user` |

### Organization (owner) endpoints

| Method | Path | Dependency | Service |
|--------|------|------------|---------|
| GET | `/organizations/{org_id}/orders/` | `require_org_editor` | `list_org_orders` |
| GET | `/organizations/{org_id}/orders/{order_id}` | `require_org_editor` + `get_org_order_or_404` | `get_order` |
| PATCH | `/organizations/{org_id}/orders/{order_id}/offer` | `require_org_editor` + `get_org_order_or_404` | `offer_order` |
| PATCH | `/organizations/{org_id}/orders/{order_id}/reject` | `require_org_editor` + `get_org_order_or_404` | `reject_order` |
| PATCH | `/organizations/{org_id}/orders/{order_id}/cancel` | `require_org_editor` + `get_org_order_or_404` | `cancel_order_by_org` |

---

## Integration with `app/main.py`

Register the orders router:

```python
from app.orders.router import router as orders_router
application.include_router(orders_router)
```

---

## Decisions & Notes

- **Lazy evaluation for auto-transitions**: `confirmed → active` and `active → finished` are triggered on read, not by a background job. Marked with `# TODO: Replace with Temporal workflow` for future migration.
- **State machine is pure**: No ORM, no framework imports. Only depends on `OrderStatus` enum and `AppValidationError`. Independently testable.
- **Dependencies handle auth**: Router receives pre-validated `Order` objects from dependency injection. Service functions don't re-check permissions.
- **Approach B chosen**: State machine as a separate module over flat service or model methods, for clarity and testability.
