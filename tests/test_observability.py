import inspect

import pytest

from app.observability.tracing import _extract_span_attributes, traced


async def test_extract_string_id_params() -> None:
    async def sample_func(org_id: str, member_id: str) -> None: ...

    sig = inspect.signature(sample_func)
    attrs = _extract_span_attributes(sig, ("org-123", "mem-456"), {})
    assert attrs == {"app.org_id": "org-123", "app.member_id": "mem-456"}


async def test_extract_model_objects() -> None:
    class FakeUser:
        id: str = "usr-abc"

    async def sample_func(user: FakeUser) -> None: ...

    sig = inspect.signature(sample_func)
    attrs = _extract_span_attributes(sig, (FakeUser(),), {})
    assert attrs == {"app.user_id": "usr-abc"}


async def test_extract_ignores_unknown_params() -> None:
    async def sample_func(name: str, count: int) -> None: ...

    sig = inspect.signature(sample_func)
    attrs = _extract_span_attributes(sig, ("hello", 42), {})
    assert attrs == {}


async def test_traced_decorator_preserves_return_value() -> None:
    @traced
    async def add(a: int, b: int) -> int:
        return a + b

    result = await add(2, 3)
    assert result == 5


async def test_traced_decorator_propagates_exceptions() -> None:
    @traced
    async def fail() -> None:
        msg = "boom"
        raise ValueError(msg)

    with pytest.raises(ValueError, match="boom"):
        await fail()
