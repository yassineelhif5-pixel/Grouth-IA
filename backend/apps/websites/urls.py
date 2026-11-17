from rest_framework.routers import SimpleRouter

from .views import WebsitePageViewSet, WebsiteViewSet

router = SimpleRouter(trailing_slash=False)
router.register("websites", WebsiteViewSet, basename="websites")
router.register("website-pages", WebsitePageViewSet, basename="website-pages")
urlpatterns = router.urls
