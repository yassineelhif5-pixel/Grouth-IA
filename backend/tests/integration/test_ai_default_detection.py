"""Auto-detect a valid key and set the default model, with a suggested provider priority order.
Mutates global (platform) AI config/routing, so it restores the seeded default at the end to stay isolated."""
import pytest

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "logs"])


def _reset(admin_conn):
    admin_conn.execute("DELETE FROM public.ai_provider_configurations WHERE tenant_id IS NULL")
    admin_conn.execute("""UPDATE public.ai_feature_routes SET is_enabled = (m.code = 'claude-sonnet-5-5')
                          FROM public.ai_models m WHERE m.id = ai_feature_routes.model_id
                            AND ai_feature_routes.tenant_id IS NULL AND ai_feature_routes.feature_code = '*'""")
    admin_conn.execute("""DELETE FROM public.ai_feature_routes WHERE tenant_id IS NULL AND feature_code = '*'
                          AND model_id NOT IN (SELECT id FROM public.ai_models WHERE code = 'claude-sonnet-5-5')""")


def test_adding_a_key_auto_selects_the_default(make_user, admin_conn):
    c = make_user(pilot=True)["client"]
    try:
        # no key anywhere → the AI has no usable model
        st = c.get("/api/v1/pilot/ai").json()
        assert st["default_model"] == "claude-sonnet-5-5" and st["effective_model"] is None

        # add an OpenAI key → the system detects it and switches the default automatically (Anthropic still keyless)
        after = c.post("/api/v1/pilot/ai", {"operation": "set_key", "provider_code": "openai", "api_key": "sk-openai-" + "x" * 24}, format="json").json()
        assert after["effective_model"] == "gpt-4o"  # flagship picked over mini/reasoner variants
        assert after["default_model"] == "gpt-4o"     # default now points at the usable provider
        cipher = admin_conn.execute("""SELECT api_key_ciphertext FROM public.ai_provider_configurations c
                                        JOIN public.ai_providers p ON p.id=c.provider_id WHERE p.code='openai' AND c.deleted_at IS NULL""").fetchone()[0]
        assert "sk-openai-" not in cipher  # stored encrypted

        # add an Anthropic key too, then ask for automatic choice → Anthropic wins by the suggested priority order
        c.post("/api/v1/pilot/ai", {"operation": "set_key", "provider_code": "anthropic", "api_key": "sk-ant-" + "y" * 24}, format="json")
        auto = c.post("/api/v1/pilot/ai", {"operation": "auto_default"}, format="json").json()
        assert auto["default_model"] == "claude-sonnet-5-5" and auto["suggested_model"] == "claude-sonnet-5-5"
    finally:
        _reset(admin_conn)
