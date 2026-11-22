from django.urls import path

from .views import (
    MarketingChatView,\n    MarketingCampaignsView,
    MarketingConversationsView,
    MarketingProfileView,
    MarketingStrategiesView,
    MarketingStrategyApproveView,
    MarketingStrategyDetailView,
)

urlpatterns = [
    path("marketing/profile", MarketingProfileView.as_view()),
    path("marketing/conversations", MarketingConversationsView.as_view()),
    path("marketing/chat", MarketingChatView.as_view()),
    path("marketing/strategies", MarketingStrategiesView.as_view()),\n    path("marketing/campaigns", MarketingCampaignsView.as_view()),
    path("marketing/strategies/<uuid:strategy_id>", MarketingStrategyDetailView.as_view()),
    path("marketing/strategies/<uuid:strategy_id>/approve", MarketingStrategyApproveView.as_view()),
]
