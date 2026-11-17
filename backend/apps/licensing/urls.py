from django.urls import path

from .views import LicenseRequestView, LicenseView, PilotPlanView, PilotTenantLicenseView

urlpatterns = [
    path("license", LicenseView.as_view()),
    path("license/requests", LicenseRequestView.as_view()),
    path("pilot/plans", PilotPlanView.as_view()),
    path("pilot/tenants/<uuid:tenant_id>/license", PilotTenantLicenseView.as_view()),
]
