from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import ConnectorAccountViewSet, ConnectorCatalogView, PilotConnectorAuthorizationView

router = SimpleRouter(trailing_slash=False)
router.register("connector-accounts", ConnectorAccountViewSet, basename="connector-accounts")
urlpatterns = [
    path("connectors", ConnectorCatalogView.as_view()),
    path("pilot/tenants/<uuid:tenant_id>/connectors", PilotConnectorAuthorizationView.as_view()),
] + router.urls
