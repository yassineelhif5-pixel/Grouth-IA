from rest_framework.routers import SimpleRouter

from . import views as v

r = SimpleRouter(trailing_slash=False)
r.register("content/items", v.ContentViewSet, basename="content-items")
r.register("content/projects", v.ProjectViewSet, basename="content-projects")
r.register("content/categories", v.CategoryViewSet, basename="content-categories")
r.register("content/schedules", v.ScheduleViewSet, basename="content-schedules")
r.register("pages", v.PageViewSet, basename="pages")
r.register("page-templates", v.TemplateViewSet, basename="page-templates")
urlpatterns = r.urls
