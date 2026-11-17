from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import SchedulerRunsView, SchedulerTaskViewSet, SchedulerV2ViewSet, WorkflowViewSet

router = SimpleRouter(trailing_slash=False)
router.register("schedulers", SchedulerV2ViewSet, basename="schedulers")
router.register("workflows", WorkflowViewSet, basename="workflows")
router.register("scheduler-tasks", SchedulerTaskViewSet, basename="scheduler-tasks")
urlpatterns = [path("scheduler-runs", SchedulerRunsView.as_view())] + router.urls
