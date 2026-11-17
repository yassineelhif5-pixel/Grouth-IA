from rest_framework.response import Response

from apps.core.db import fetch_all_dict
from apps.core.views import GrowthAPIView

from . import engine


class IntelligenceView(GrowthAPIView):
    permission_map = {"GET": "intelligence.read", "POST": "intelligence.manage"}
    required_module = "intelligence"

    def get(self, request):
        tid = request.tenant.tenant_id
        return Response({
            "recommendations": fetch_all_dict("""SELECT id, title, body, priority, status, rule_code, sources, justification, confidence, impact, difficulty,
                                                        risks, actions, nature, created_at FROM public.growth_recommendations WHERE tenant_id = %s AND deleted_at IS NULL
                                                  ORDER BY (status = 'open') DESC, priority, created_at DESC LIMIT 200""", [tid]),
            "snapshot": (fetch_all_dict("SELECT data, created_at FROM public.growth_intelligence_snapshots WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 1", [tid]) or [None])[0],
            "learning": fetch_all_dict("SELECT lesson, data, created_at FROM public.growth_learning_events WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 50", [tid]),
        })

    def post(self, request):
        if request.data.get("op") == "decide":
            engine.decide(request.data["id"], bool(request.data.get("accept")), request.data.get("comment", ""))
            return self.get(request)
        return Response(engine.run_cycle())
