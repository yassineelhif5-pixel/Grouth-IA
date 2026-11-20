from django.urls import path

from .views import LicenseRequestView, LicenseView, PilotPlanView, PilotTenantLicenseView

urlpatterns = [
    path("license", LicenseView.as_view()),
    path("license/requests", LicenseRequestView.as_view()),
    path("pilot/plans", PilotPlanView.as_view()),
    path("pilot/tenants/<uuid:tenant_id>/license", PilotTenantLicenseView.as_view()),
]

from .billing import CheckoutView, PlanCatalogView, StripeWebhookView  # noqa: E402

urlpatterns += [path("billing/plans", PlanCatalogView.as_view()), path("billing/checkout", CheckoutView.as_view()), path("webhooks/stripe", StripeWebhookView.as_view())]
