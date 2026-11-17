from django.urls import path

from .views import IntelligenceView

urlpatterns = [path("intelligence", IntelligenceView.as_view())]
