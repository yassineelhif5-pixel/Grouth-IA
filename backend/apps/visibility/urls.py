from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    AiVisibilityQuestionViewSet,
    AiVisibilityView,
    AssetDownloadView,
    AssistantView,
    KpiView,
    ProgrammeView,
    RecommendationViewSet,
    TenantRoadmapViewSet,
    VisibilityAuditViewSet,
    VisibilityProfileViewSet,
)

router = SimpleRouter(trailing_slash=False)
router.register("visibility/profiles", VisibilityProfileViewSet, basename="visibility-profiles")
router.register("visibility/audits", VisibilityAuditViewSet, basename="visibility-audits")
router.register("visibility/recommendations", RecommendationViewSet, basename="visibility-recommendations")
router.register("visibility/roadmap", TenantRoadmapViewSet, basename="visibility-roadmap")
router.register("visibility/questions", AiVisibilityQuestionViewSet, basename="visibility-questions")
urlpatterns = [path("visibility/programmes", ProgrammeView.as_view()), path("visibility/assistant", AssistantView.as_view()),
               path("visibility/kpis", KpiView.as_view()), path("visibility/ai", AiVisibilityView.as_view()),
               path("visibility/assets/<uuid:asset_id>/download", AssetDownloadView.as_view())] + router.urls
