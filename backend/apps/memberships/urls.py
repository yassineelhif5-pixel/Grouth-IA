from django.urls import path

from .views import (
    LicensesView,
    MemberDetailView,
    MemberLicenseView,
    MemberListView,
    PilotTenantLicensesView,
    PilotTenantMembersView,
    PilotTenantMemberView,
)

urlpatterns = [path("members", MemberListView.as_view()), path("members/<uuid:member_id>", MemberDetailView.as_view()),
               path("members/<uuid:member_id>/license", MemberLicenseView.as_view()), path("licenses", LicensesView.as_view()),
               path("pilot/tenants/<uuid:tenant_id>/members", PilotTenantMembersView.as_view()),
               path("pilot/tenants/<uuid:tenant_id>/members/<uuid:member_id>", PilotTenantMemberView.as_view()),
               path("pilot/tenants/<uuid:tenant_id>/licenses", PilotTenantLicensesView.as_view())]
