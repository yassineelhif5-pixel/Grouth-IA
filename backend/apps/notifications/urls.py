from django.urls import path

from .views import MarkReadView, MyNotificationsView

urlpatterns = [path("notifications", MyNotificationsView.as_view()), path("notifications/read", MarkReadView.as_view())]
