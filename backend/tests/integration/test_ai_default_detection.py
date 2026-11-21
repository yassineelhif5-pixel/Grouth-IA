"""Auto-detect a valid key and set the default model, with a suggested provider priority order."""
import pytest

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "logs"])


def _pilot(make_user):
    p = make_user(pilot=True)
    return p["client"]


def test_adding_a_key_auto_selects_the_default(make_user, admin_conn):
    c = _pilot(make_user)
    # no key anywhere → the AI has no usable model
    st = c.get("/api/v1/pilot/ai").json()
    assert st["default_model"] == "claude-sonnet-5-5" and st["effective_model"] is None

    # add an OpenAI key → the system detects it and switches the default automatically (Anthropic still keyless)
    r = c.post("/api/v1/pilot/ai", {"operation": "set_key", "provider_code": "openai", "api_key": "sk-openai-" + "x" * 24}, format="json")
    assert r.status_code == 200, r.content
    after = r.json()
    assert after["effective_model"] and after["effective_model"].startswith("gpt-")
    assert after["default_model"] == after["effective_model"]  # default now points at the usable provider
    # the key is stored encrypted
    cipher = admin_conn.execute("""SELECT api_key_ciphertext FROM public.ai_provider_configurations c
                                    JOIN public.ai_providers p ON p.id=c.provider_id WHERE p.code='openai' AND c.deleted_at IS NULL""").fetchone()[0]
    assert "sk-openai-" not in cipher

    # add an Anthropic key too, then ask for automatic choice → Anthropic wins by the suggested priority order
    c.post("/api/v1/pilot/ai", {"operation": "set_key", "provider_code": "anthropic", "api_key": "sk-ant-" + "y" * 24}, format="json")
    auto = c.post("/api/v1/pilot/ai", {"operation": "auto_default"}, format="json").json()
    assert auto["default_model"] == "claude-sonnet-5-5" and auto["effective_model"] == "claude-sonnet-5-5"
    # the suggested order is exposed so the UI can offer it
    assert auto["suggested_model"] == "claude-sonnet-5-5"
