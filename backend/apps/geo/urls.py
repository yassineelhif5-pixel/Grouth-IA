from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v

r = SimpleRouter(trailing_slash=False)
r.register("geo/queries", v.QueryViewSet, basename="geo-queries")
r.register("geo/brands", v.BrandViewSet, basename="geo-brands")
r.register("geo/recommendations", v.RecommendationViewSet, basename="geo-recommendations")
r.register("geo/audits", v.AuditViewSet, basename="geo-audits")
r.register("geo/snapshots", v.SnapshotViewSet, basename="geo-snapshots")
urlpatterns = [path("geo/products/<uuid:product_id>", v.GeoActionsView.as_view())] + r.urls
