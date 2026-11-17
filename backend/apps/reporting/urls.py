from django.urls import path

from .views import PilotUsageView, TenantDashboardView

urlpatterns = [path("dashboard", TenantDashboardView.as_view()), path("pilot/usage", PilotUsageView.as_view())]
