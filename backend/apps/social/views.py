from django.http import HttpResponse
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.crud import crud
from apps.core.exceptions import BusinessError
from apps.core.tenancy import has_permission

from . import services as s
from .models import SocialAccount, SocialPublication, VideoAsset, VideoProject, VideoScene, VideoScript, VideoStoryboard

AccountViewSet = crud(SocialAccount, module="social", perm="social", filters=["platform", "product", "status"])
_Pub = crud(SocialPublication, module="social", perm="social", filters=["social_account", "status", "content"], ordering=["-created_at"])


class PublicationViewSet(_Pub):
    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        if not has_permission(request.tenant.tenant_id, request.user.id, "social.publish"):
            raise BusinessError("social.publish required", "forbidden", status_code=403)
        self.get_object()
        return Response(s.request_publish(str(pk)))

    @action(detail=False, methods=["post"])
    def generate(self, request):
        return Response({"body": s.generate_post(request.data.get("product_id"), request.data.get("platform", "linkedin"), request.data.get("topic", ""))})


_V = crud(VideoProject, module="video", perm="video", filters=["product", "status", "format"])


class VideoProjectViewSet(_V):
    @action(detail=True, methods=["post"])
    def script(self, request, pk=None):
        self.get_object()
        return Response({"script_id": s.generate_script(str(pk), request.data.get("brief", ""))})

    @action(detail=True, methods=["post"])
    def render(self, request, pk=None):
        self.get_object()
        return Response(s.request_render(str(pk), request.data.get("provider")))

    @action(detail=False, methods=["get"], url_path=r"storyboards/(?P<sb>[^/.]+)/subtitles.srt")
    def subtitles(self, request, sb=None):
        return HttpResponse(s.subtitles_srt(sb), content_type="application/x-subrip")


ScriptViewSet = crud(VideoScript, module="video", perm="video", filters=["project"])
StoryboardViewSet = crud(VideoStoryboard, module="video", perm="video", filters=["project"])
SceneViewSet = crud(VideoScene, module="video", perm="video", filters=["storyboard"], ordering=["position"])
AssetViewSet = crud(VideoAsset, module="video", perm="video", filters=["project", "source"])
