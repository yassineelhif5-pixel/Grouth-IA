from django.urls import path

from .views import AITestView, AIUsageView, PilotAIProvidersView

urlpatterns = [path("pilot/ai", PilotAIProvidersView.as_view()), path("ai/test", AITestView.as_view()), path("ai/usage", AIUsageView.as_view())]
