from django.urls import path

from .views import MemberDetailView, MemberListView

urlpatterns = [path("members", MemberListView.as_view()), path("members/<uuid:member_id>", MemberDetailView.as_view())]
