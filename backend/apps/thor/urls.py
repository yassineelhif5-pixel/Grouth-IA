from django.urls import path

from .views import ThorChatView, ThorMemoryView

urlpatterns = [path("thor/chat", ThorChatView.as_view()), path("thor/memory", ThorMemoryView.as_view())]
