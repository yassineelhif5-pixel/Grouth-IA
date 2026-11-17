from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import ConnectorAccountViewSet, ConnectorCatalogView, PilotConnectorAuthorizationView

router = SimpleRouter(trailing_slash=False)
router.register("connector-accounts", ConnectorAccountViewSet, basename="connector-accounts")
urlpatterns = [
    path("connectors", ConnectorCatalogView.as_view()),
    path("pilot/tenants/<uuid:tenant_id>/connectors", PilotConnectorAuthorizationView.as_view()),
] + router.urls

from . import views_v2 as v2  # noqa: E402

urlpatterns += [
    path("connector-accounts/<uuid:account_id>/credentials", v2.CredentialsView.as_view()),
    path("connector-accounts/<uuid:account_id>/test", v2.TestView.as_view()),
    path("connector-accounts/<uuid:account_id>/disconnect", v2.DisconnectView.as_view()),
    path("connector-accounts/<uuid:account_id>/oauth/start", v2.OAuthStartView.as_view()),
    path("connectors/oauth/callback", v2.OAuthCallbackView.as_view()),
    path("connectors/status", v2.ConnectorStatusView.as_view()),
    path("pilot/oauth-clients", v2.PilotOAuthClientView.as_view()),
]
