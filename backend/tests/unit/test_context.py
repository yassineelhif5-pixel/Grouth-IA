"""Pure unit tests (no Django / DB): context propagation & redaction."""
import uuid

import pytest

from apps.core.context import ExecutionContext, get_context, parse_uuid, reset_context, set_context


def test_headers_roundtrip_keeps_correlation_chain():
    ctx = ExecutionContext(user_id=str(uuid.uuid4()), tenant_id=str(uuid.uuid4()), actor_type="user", is_platform=False)
    restored = ExecutionContext.from_headers(ctx.to_headers())
    assert restored.correlation_id == ctx.correlation_id
    assert restored.request_id == ctx.request_id
    assert restored.tenant_id == ctx.tenant_id and restored.user_id == ctx.user_id
    assert restored.actor_type == "celery"  # executed by a worker
    assert restored.is_platform is False


def test_platform_flag_propagates_only_when_true():
    assert ExecutionContext.from_headers(ExecutionContext(is_platform=True).to_headers()).is_platform is True


def test_malformed_headers_never_inject_ids():
    restored = ExecutionContext.from_headers({"growth_tenant_id": "'; DROP TABLE x;--", "growth_user_id": "nope"})
    assert restored.tenant_id is None and restored.user_id is None
    assert parse_uuid(restored.correlation_id)


def test_invalid_actor_type_rejected():
    with pytest.raises(ValueError):
        ExecutionContext().with_(actor_type="root")


def test_context_var_isolation():
    a = ExecutionContext(tenant_id=str(uuid.uuid4()))
    token = set_context(a)
    assert get_context().tenant_id == a.tenant_id
    reset_context(token)
    assert get_context().tenant_id != a.tenant_id
