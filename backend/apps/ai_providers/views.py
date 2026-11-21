from rest_framework.response import Response

from apps.audit.services import record_audit
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.core.secrets import encrypt_json
from apps.core.views import GrowthAPIView

from .gateway import AINotConfigured, complete


def _set_default_model(code: str) -> None:
    """Make `code` the default model for every feature without a specific route (global '*' route)."""
    if not fetch_one("SELECT 1 FROM public.ai_models WHERE code = %s AND is_enabled", [code]):
        raise BusinessError("Modèle inconnu", "invalid")
    fetch_one("""UPDATE public.ai_feature_routes SET is_enabled = false WHERE tenant_id IS NULL AND feature_code = '*'
                  AND model_id <> (SELECT id FROM public.ai_models WHERE code = %s) RETURNING 1""", [code])
    if not fetch_one("""UPDATE public.ai_feature_routes SET is_enabled = true, priority = 1 WHERE tenant_id IS NULL AND feature_code = '*'
                         AND model_id = (SELECT id FROM public.ai_models WHERE code = %s) RETURNING 1""", [code]):
        fetch_one("""INSERT INTO public.ai_feature_routes (tenant_id, feature_code, model_id, priority, is_enabled)
                     SELECT NULL, '*', id, 1, true FROM public.ai_models WHERE code = %s RETURNING id""", [code])


def _default_route_usable() -> bool:
    """True when the stored default model's provider actually has a usable key (so the AI works without fallback)."""
    from .gateway import routes
    rows = routes("content.generation", None)
    if not rows:
        return False
    default = fetch_one("""SELECT m.code FROM public.ai_feature_routes r JOIN public.ai_models m ON m.id = r.model_id
                            WHERE r.tenant_id IS NULL AND r.feature_code = '*' AND r.is_enabled ORDER BY r.priority LIMIT 1""")
    return bool(default) and rows[0]["model"] == default[0]


class PilotAIProvidersView(GrowthAPIView):
    """PILOTE: providers, encrypted keys, models (prices), feature routes with priority/fallback."""
    platform_scoped = True

    def get(self, request):
        from .gateway import auto_default_model, env_key, routes
        default = fetch_one("""SELECT m.code FROM public.ai_feature_routes r JOIN public.ai_models m ON m.id = r.model_id
                                WHERE r.tenant_id IS NULL AND r.feature_code = '*' AND r.is_enabled ORDER BY r.priority LIMIT 1""")
        routed = routes("content.generation", None)  # what the gateway actually uses right now (empty if the default's key is missing)
        auto = auto_default_model(None)
        effective = routed[0]["model"] if routed else (auto["model"] if auto else None)  # display: show the model that would serve
        return Response({
            "default_model": default[0] if default else None,
            "effective_model": effective,  # differs from default when the default's key is missing but another provider has one
            "suggested_model": auto["model"] if auto else None,  # best available by the suggested priority order
            "env_keys": {p: bool(env_key(p)) for p in ("anthropic", "openai", "google", "deepseek", "moonshot", "openrouter", "xai", "mistral", "groq", "perplexity", "cohere")},
            "providers": fetch_all_dict("""SELECT p.code, p.name, p.api_style, p.is_enabled, c.id AS config_id, c.base_url, c.priority,
                                                  (c.api_key_ciphertext IS NOT NULL) AS has_key, c.last_test_at, c.last_test_status
                                             FROM public.ai_providers p LEFT JOIN public.ai_provider_configurations c
                                               ON c.provider_id = p.id AND c.tenant_id IS NULL AND c.deleted_at IS NULL ORDER BY p.code"""),
            "models": fetch_all_dict("""SELECT m.id, p.code AS provider, m.code, m.name, m.context_window, m.input_cost_per_mtok_cents,
                                               m.output_cost_per_mtok_cents, m.is_enabled FROM public.ai_models m
                                          JOIN public.ai_providers p ON p.id = m.provider_id ORDER BY p.code, m.code"""),
            "routes": fetch_all_dict("""SELECT r.id, r.feature_code, m.code AS model, r.priority, r.quality, r.is_enabled, r.tenant_id
                                          FROM public.ai_feature_routes r JOIN public.ai_models m ON m.id = r.model_id
                                         ORDER BY r.feature_code, r.priority"""),
        })

    def post(self, request):
        op = request.data.get("operation")
        d = request.data
        if op == "set_key":
            if not d.get("api_key") and d.get("provider_code") != "ollama":
                raise BusinessError("api_key required", "invalid")
            fetch_one("""INSERT INTO public.ai_provider_configurations (provider_id, api_key_ciphertext, base_url, priority, settings)
                         SELECT id, %s, %s, %s, %s::jsonb FROM public.ai_providers WHERE code = %s
                         ON CONFLICT (tenant_id, provider_id) WHERE deleted_at IS NULL DO UPDATE SET api_key_ciphertext = EXCLUDED.api_key_ciphertext,
                           base_url = EXCLUDED.base_url, priority = EXCLUDED.priority, settings = EXCLUDED.settings RETURNING id""",
                      [encrypt_json({"api_key": d.get("api_key", "")}), d.get("base_url"), int(d.get("priority", 100)),
                       __import__("json").dumps(d.get("settings") or {}), d["provider_code"]])
            # auto-detect: if the AI was not usable (current default provider has no key), make the best available model the default
            from .gateway import auto_default_model, routes
            if not routes("content.generation", None):
                pass  # no usable route even after storing — nothing to switch to
            elif not _default_route_usable():
                best = auto_default_model(None)
                if best:
                    _set_default_model(best["model"])
        elif op == "upsert_model":
            fetch_one("""INSERT INTO public.ai_models (provider_id, code, name, context_window, input_cost_per_mtok_cents, output_cost_per_mtok_cents)
                         SELECT id, %s, %s, %s, %s, %s FROM public.ai_providers WHERE code = %s
                         ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, context_window = EXCLUDED.context_window,
                           input_cost_per_mtok_cents = EXCLUDED.input_cost_per_mtok_cents,
                           output_cost_per_mtok_cents = EXCLUDED.output_cost_per_mtok_cents RETURNING id""",
                      [d["model_code"], d.get("name") or d["model_code"], d.get("context_window"), d.get("input_cost_per_mtok_cents"),
                       d.get("output_cost_per_mtok_cents"), d["provider_code"]])
        elif op == "route":
            fetch_one("""INSERT INTO public.ai_feature_routes (feature_code, model_id, priority, quality, is_enabled)
                         SELECT %s, id, %s, %s, %s FROM public.ai_models WHERE code = %s
                         ON CONFLICT (tenant_id, feature_code, model_id) DO UPDATE SET priority = EXCLUDED.priority,
                           quality = EXCLUDED.quality, is_enabled = EXCLUDED.is_enabled RETURNING id""",
                      [d["feature_code"], int(d.get("priority", 1)), d.get("quality", "standard"), bool(d.get("is_enabled", True)), d["model_code"]])
        elif op == "set_default":  # default model for every feature without a specific route
            _set_default_model(d.get("model_code"))
        elif op == "auto_default":  # pick the best available model by the suggested priority order
            from .gateway import auto_default_model
            best = auto_default_model(None)
            if not best:
                raise BusinessError("Aucune clé valide détectée : ajoutez une clé de fournisseur", "no_key")
            _set_default_model(best["model"])
        else:
            raise BusinessError("Unknown operation", "invalid")
        record_audit(f"pilot.ai.{op}", "ai_providers", after={k: v for k, v in d.items() if k != "api_key"})
        return self.get(request)


class AITestView(GrowthAPIView):
    """Real call through the gateway for a feature (tenant context: usage is logged and billed to the tenant)."""
    permission_map = {"POST": "ai.usage.read"}

    def post(self, request):
        try:
            r = complete(request.data.get("feature", "thor.chat"), [{"role": "user", "content": "Reply with the single word: OK"}],
                         system="You are a connectivity test.", max_tokens=5)
            return Response({"status": "tested", "provider": r.provider, "model": r.model, "duration_ms": r.duration_ms,
                             "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                             "cost_cents": float(r.cost_cents) if r.cost_cents is not None else None})
        except AINotConfigured as e:
            return Response({"status": "not_configured", "error": e.message})


class AIUsageView(GrowthAPIView):
    permission_map = {"GET": "ai.usage.read"}

    def get(self, request):
        return Response(fetch_all_dict(
            """SELECT date_trunc('day', created_at)::date AS day, feature_code, provider_code, model_code, count(*) AS calls,
                      sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens, sum(cost_cents) AS cost_cents,
                      count(*) FILTER (WHERE status <> 'succeeded') AS errors
                 FROM public.ai_execution_logs WHERE tenant_id = %s AND created_at > now() - interval '30 days'
                GROUP BY 1,2,3,4 ORDER BY 1 DESC""", [request.tenant.tenant_id]))
