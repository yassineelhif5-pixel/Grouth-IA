from django.urls import path

from .login import LoginView, UsernameAvailabilityView
from .views import DemoSignupView, MeView

urlpatterns = [path("me", MeView.as_view()), path("signup/demo", DemoSignupView.as_view()),
               path("auth/login", LoginView.as_view()), path("auth/username-available", UsernameAvailabilityView.as_view())]
