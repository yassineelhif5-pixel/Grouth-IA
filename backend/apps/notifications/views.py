from rest_framework.response import Response

from apps.core.db import fetch_all_dict, fetch_one
from apps.core.views import GrowthAPIView


class MyNotificationsView(GrowthAPIView):
    def get(self, request):
        return Response(fetch_all_dict(
            """SELECT id, category, title, body, link, severity, read_at, created_at FROM public.notifications
                WHERE tenant_id = %s AND user_id = %s ORDER BY created_at DESC LIMIT 100""",
            [request.tenant.tenant_id, request.user.id]))


class MarkReadView(GrowthAPIView):
    def post(self, request):
        # notifications is append-only: read state is tracked through a dedicated controlled function
        ids = [str(i) for i in request.data.get("ids", [])][:200]
        updated = fetch_one("SELECT app.mark_notifications_read(%s::uuid[])", [ids])[0] if ids else 0
        return Response({"updated": updated})
