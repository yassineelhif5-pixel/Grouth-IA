from django.urls import path

from . import views as v

urlpatterns = [
    path("approvals", v.ApprovalsView.as_view()),
    path("approvals/<uuid:approval_id>/decide", v.ApprovalDecisionView.as_view()),
    path("growth-policies", v.GrowthPoliciesView.as_view()),
    path("pilot/capabilities", v.PilotCapabilitiesView.as_view()),
    path("pilot/tenants/<uuid:tenant_id>/suspensions", v.PilotAgentSuspensionView.as_view()),
]
