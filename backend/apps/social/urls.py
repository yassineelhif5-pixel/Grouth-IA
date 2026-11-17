from rest_framework.routers import SimpleRouter

from . import views as v

r = SimpleRouter(trailing_slash=False)
r.register("social/accounts", v.AccountViewSet, basename="social-accounts")
r.register("social/publications", v.PublicationViewSet, basename="social-publications")
r.register("video/projects", v.VideoProjectViewSet, basename="video-projects")
r.register("video/scripts", v.ScriptViewSet, basename="video-scripts")
r.register("video/storyboards", v.StoryboardViewSet, basename="video-storyboards")
r.register("video/scenes", v.SceneViewSet, basename="video-scenes")
r.register("video/assets", v.AssetViewSet, basename="video-assets")
urlpatterns = r.urls
