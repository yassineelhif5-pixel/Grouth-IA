from django.http import HttpResponse
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.crud import crud
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.core.tenancy import has_permission

from . import services as s
from .models import BuilderPage, BuilderTemplate, ContentCategory, ContentProject, GeneratedContent, PublicationSchedule

_C = crud(GeneratedContent, module="content", perm="content", filters=["project", "product", "status", "content_type", "channel"],
          search=["title", "keyword"])


class ContentViewSet(_C):
    def perform_create(self, serializer):
        super().perform_create(serializer)
        obj = serializer.instance
        if obj.body:
            s.create_version(str(obj.pk), obj.title, obj.body, "manual", note="initial")

    def perform_update(self, serializer):
        before = serializer.instance.body
        super().perform_update(serializer)
        obj = serializer.instance
        if "body" in serializer.validated_data and obj.body != before:
            s.create_version(str(obj.pk), obj.title, obj.body or "", "manual", note=self.request.data.get("change_reason"))
            s.score_content(str(obj.pk))

    @action(detail=True, methods=["post"])
    def ai(self, request, pk=None):
        """operation: generate | rewrite | correct | translate | optimize_seo | optimize_geo (async, persisted job)."""
        from .tasks import generate_task
        self.get_object()
        op = request.data.get("operation", "generate")
        if op not in s.OPERATIONS:
            raise BusinessError("unknown operation", "invalid")
        generate_task.delay_traced(str(pk), op, request.data.get("brief", ""), request.data.get("target_language"))
        return Response({"status": "queued"}, status=202)

    @action(detail=True, methods=["get"])
    def versions(self, request, pk=None):
        self.get_object()
        return Response(fetch_all_dict("""SELECT version, title, source, model_code, prompt_version, author_id, change_note, created_at, body
                                          FROM public.content_versions WHERE content_id = %s ORDER BY version DESC""", [pk]))

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        obj = self.get_object()
        v = fetch_one("SELECT title, body FROM public.content_versions WHERE content_id = %s AND version = %s", [pk, request.data.get("version")])
        if not v:
            raise BusinessError("version not found", "not_found", status_code=404)
        from apps.core.services import audited_update
        audited_update(obj, {"title": v[0], "body": v[1]}, action="content.restored", module="content", reason=f"restore v{request.data.get('version')}")
        n = s.create_version(str(pk), v[0], v[1] or "", "restore", note=f"restore of v{request.data.get('version')}")
        return Response({"version": n})

    @action(detail=True, methods=["post"])
    def workflow(self, request, pk=None):
        op = request.data.get("op")
        if op not in s.TRANSITIONS:
            raise BusinessError("unknown op", "invalid")
        if op in ("approve", "reject") and not has_permission(request.tenant.tenant_id, request.user.id, "content.approve"):
            raise BusinessError("content.approve required", "forbidden", status_code=403)
        self.get_object()
        return Response({"status": s.transition(str(pk), op, request.data.get("comment", ""))})

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        if not has_permission(request.tenant.tenant_id, request.user.id, "content.publish"):
            raise BusinessError("content.publish required", "forbidden", status_code=403)
        self.get_object()
        return Response(s.request_publication(str(pk), request.data["connector_account_id"]))

    @action(detail=True, methods=["post"])
    def sources(self, request, pk=None):
        self.get_object()
        return Response(s.verify_sources(str(pk)))

    @action(detail=True, methods=["get"])
    def scores(self, request, pk=None):
        self.get_object()
        return Response(s.score_content(str(pk)))


_P = crud(BuilderPage, module="pages", perm="pages", filters=["product", "website", "status", "page_type"], search=["title", "slug"])


class PageViewSet(_P):
    def perform_create(self, serializer):
        super().perform_create(serializer)
        s.save_page_version(str(serializer.instance.pk))

    def perform_update(self, serializer):
        super().perform_update(serializer)
        s.save_page_version(str(serializer.instance.pk))

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        p = self.get_object()
        return HttpResponse(s.render_page(p.title, p.sections, p.seo), content_type="text/html; charset=utf-8",
                            headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})

    @action(detail=True, methods=["get"])
    def versions(self, request, pk=None):
        self.get_object()
        return Response(s.page_versions(str(pk)))

    @action(detail=True, methods=["post"])
    def workflow(self, request, pk=None):
        p = self.get_object()
        nxt = {"submit": ("draft", "review"), "approve": ("review", "approved"), "reject": ("review", "draft")}.get(request.data.get("op"))
        if not nxt or p.status != nxt[0]:
            raise BusinessError("invalid transition", "invalid_state", status_code=409)
        from apps.core.services import audited_update
        audited_update(p, {"status": nxt[1]}, action=f"page.{request.data['op']}", module="pages")
        return Response({"status": nxt[1]})

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        if not has_permission(request.tenant.tenant_id, request.user.id, "pages.publish"):
            raise BusinessError("pages.publish required", "forbidden", status_code=403)
        self.get_object()
        return Response(s.request_page_publication(str(pk)))


ProjectViewSet = crud(ContentProject, module="content", perm="content", filters=["product", "status"])
CategoryViewSet = crud(ContentCategory, module="content", perm="content")
ScheduleViewSet = crud(PublicationSchedule, module="content", perm="content", write="publish", filters=["content", "status"])
TemplateViewSet = crud(BuilderTemplate, module="pages", perm="pages")
