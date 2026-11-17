from rest_framework.response import Response

from apps.core.db import fetch_all_dict, fetch_one
from apps.core.views import GrowthAPIView

from . import engine


class ThorChatView(GrowthAPIView):
    permission_map = {"*": "thor.use"}
    required_module = "thor"

    def get(self, request):
        cid = request.query_params.get("conversation_id")
        if cid:
            return Response(fetch_all_dict("""SELECT m.id, m.role, m.content, m.model_code, m.provider_code, m.cost_cents, m.duration_ms, m.created_at,
                                                     (SELECT json_agg(json_build_object('tool', t.tool_name, 'status', t.status, 'duration_ms', t.duration_ms))
                                                        FROM public.thor_tool_executions t WHERE t.message_id = m.id) AS tools
                                                FROM public.thor_messages m JOIN public.thor_conversations c ON c.id = m.conversation_id
                                               WHERE m.conversation_id = %s AND c.user_id = %s AND m.tenant_id = %s ORDER BY m.created_at""",
                                           [cid, request.user.id, request.tenant.tenant_id]))
        return Response(fetch_all_dict("""SELECT id, title, product_id, status, created_at, updated_at FROM public.thor_conversations
                                           WHERE tenant_id = %s AND user_id = %s AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 100""",
                                       [request.tenant.tenant_id, request.user.id]))

    def post(self, request):
        return Response(engine.chat(request.data.get("conversation_id"), request.data["message"], request.data.get("product_id")))


class ThorMemoryView(GrowthAPIView):
    permission_map = {"*": "thor.use"}
    required_module = "thor"

    def get(self, request):
        return Response(fetch_all_dict("""SELECT id, memory_type, content, user_id IS NULL AS shared, created_at FROM public.thor_memory
                                           WHERE tenant_id = %s AND (user_id = %s OR user_id IS NULL) AND deleted_at IS NULL ORDER BY created_at DESC""",
                                       [request.tenant.tenant_id, request.user.id]))

    def post(self, request):
        return Response({"id": engine.remember(request.data["content"], request.data.get("memory_type", "fact"), bool(request.data.get("shared")))}, status=201)

    def delete(self, request):
        fetch_one("UPDATE public.thor_memory SET deleted_at = now() WHERE id = %s AND tenant_id = %s AND (user_id = %s OR user_id IS NULL) RETURNING 1",
                  [request.query_params["id"], request.tenant.tenant_id, request.user.id])
        return Response(status=204)
