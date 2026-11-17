from rest_framework.routers import SimpleRouter

from .views import ProductCompetitorViewSet, ProductGoalViewSet, ProductV2ViewSet

router = SimpleRouter(trailing_slash=False)
router.register("products", ProductV2ViewSet, basename="products")
router.register("product-goals", ProductGoalViewSet, basename="product-goals")
router.register("product-competitors", ProductCompetitorViewSet, basename="product-competitors")
urlpatterns = router.urls
