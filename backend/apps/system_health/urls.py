from django.urls import path

from .views import HealthHistoryView, HealthOverviewView, HealthRunView, IncidentsView

urlpatterns = [
    path("pilot/health", HealthOverviewView.as_view()),
    path("pilot/health/run", HealthRunView.as_view()),
    path("pilot/health/checks/<str:code>/history", HealthHistoryView.as_view()),
    path("pilot/incidents", IncidentsView.as_view()),
]
