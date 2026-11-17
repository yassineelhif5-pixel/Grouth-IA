from django.urls import path

from .views import ExportView, GlobalDashboardView, PilotUsageView, TenantDashboardView

urlpatterns = [path("dashboard", TenantDashboardView.as_view()), path("pilot/usage", PilotUsageView.as_view()),
               path("reporting/global", GlobalDashboardView.as_view()), path("reporting/export.<str:fmt>", ExportView.as_view())]
