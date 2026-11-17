from django.urls import path

from .views import DemoSignupView, MeView

urlpatterns = [path("me", MeView.as_view()), path("signup/demo", DemoSignupView.as_view())]
