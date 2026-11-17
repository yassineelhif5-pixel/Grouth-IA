from django.urls import path

from .views import InvitationAcceptView, InvitationListView, InvitationRevokeView

urlpatterns = [
    path("invitations", InvitationListView.as_view()),
    path("invitations/<uuid:invitation_id>/revoke", InvitationRevokeView.as_view()),
    path("invitations/accept", InvitationAcceptView.as_view()),
]
