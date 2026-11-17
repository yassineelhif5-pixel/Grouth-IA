from django.urls import path

from . import views as v

urlpatterns = [
    path("history/events", v.AuditEventsView.as_view()),
    path("history/activity", v.ActivityView.as_view()),
    path("history/executions", v.ExecutionsView.as_view()),
    path("history/export.csv", v.ExportCsvView.as_view()),
    path("history/trace/<uuid:correlation_id>", v.TraceView.as_view()),
    path("history/entities/<str:entity_type>/<uuid:entity_id>/versions", v.EntityVersionsView.as_view()),
    path("history/entities/<str:entity_type>/<uuid:entity_id>/compare", v.CompareVersionsView.as_view()),
    path("history/entities/<str:entity_type>/<uuid:entity_id>/restore", v.RestoreVersionView.as_view()),
    path("pilot/history/events", v.PilotAuditView.as_view()),
    path("pilot/history/executions", v.PilotExecutionsView.as_view()),
    path("pilot/history/errors", v.PilotErrorsView.as_view()),
    path("pilot/history/trace/<uuid:correlation_id>", v.PilotTraceView.as_view()),
]
