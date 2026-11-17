from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import CurrentTenantView, PilotGlobalView, PilotOverviewView, PilotTenantViewSet, TenantSettingViewSet

router = SimpleRouter(trailing_slash=False)
router.register("tenant/settings", TenantSettingViewSet, basename="tenant-settings")
router.register("pilot/tenants", PilotTenantViewSet, basename="pilot-tenants")
urlpatterns = [path("tenant", CurrentTenantView.as_view()), path("pilot/overview", PilotOverviewView.as_view()),
               path("pilot/global", PilotGlobalView.as_view())] + router.urls
