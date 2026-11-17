from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

api_v1 = [
    path("", include("apps.accounts.urls")),
    path("", include("apps.tenants.urls")),
    path("", include("apps.memberships.urls")),
    path("", include("apps.invitations.urls")),
    path("", include("apps.licensing.urls")),
    path("", include("apps.integrations.urls")),
    path("", include("apps.products.urls")),
    path("", include("apps.websites.urls")),
    path("", include("apps.scheduler.urls")),
    path("", include("apps.reporting.urls")),
    path("", include("apps.notifications.urls")),
    path("", include("apps.history.urls")),
    path("", include("apps.system_health.urls")),
    path("health/", include("apps.core.urls_health")),
    path("schema", SpectacularAPIView.as_view(), name="schema"),
    path("docs", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]

urlpatterns = [path("api/v1/", include(api_v1))]
