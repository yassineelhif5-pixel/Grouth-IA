from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core.cron import CronTickView

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
    path("", include("apps.ai_providers.urls")),
    path("", include("apps.permissions.urls")),
    path("", include("apps.seo.urls")),
    path("", include("apps.geo.urls")),
    path("", include("apps.content.urls")),
    path("", include("apps.social.urls")),
    path("", include("apps.opportunities.urls")),
    path("", include("apps.prospects.urls")),
    path("", include("apps.email_center.urls")),
    path("", include("apps.whatsapp.urls")),
    path("", include("apps.visibility.urls")),
    path("", include("apps.intelligence.urls")),
    path("", include("apps.thor.urls")),
    path("", include("apps.marketing_center.urls")),
    path("health/", include("apps.core.urls_health")),
    path("internal/cron/tick", CronTickView.as_view()),  # periodic tasks without Celery Beat (serverless)
    path("schema", SpectacularAPIView.as_view(), name="schema"),
    path("docs", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]

urlpatterns = [path("api/v1/", include(api_v1))]
