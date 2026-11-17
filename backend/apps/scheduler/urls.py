from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import SchedulerRunsView, SchedulerTaskViewSet, SchedulerViewSet

router = SimpleRouter(trailing_slash=False)
router.register("schedulers", SchedulerViewSet, basename="schedulers")
router.register("scheduler-tasks", SchedulerTaskViewSet, basename="scheduler-tasks")
urlpatterns = [path("scheduler-runs", SchedulerRunsView.as_view())] + router.urls
