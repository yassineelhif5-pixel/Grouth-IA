from rest_framework.routers import SimpleRouter

from .views import ProductCompetitorViewSet, ProductGoalViewSet, ProductViewSet

router = SimpleRouter(trailing_slash=False)
router.register("products", ProductViewSet, basename="products")
router.register("product-goals", ProductGoalViewSet, basename="product-goals")
router.register("product-competitors", ProductCompetitorViewSet, basename="product-competitors")
urlpatterns = router.urls
