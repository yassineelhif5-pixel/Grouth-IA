from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v
from .webhooks import DeliveryEventWebhook, InboundEmailWebhook

r = SimpleRouter(trailing_slash=False)
r.register("email/provider-accounts", v.ProviderAccountViewSet, basename="email-provider-accounts")
r.register("email/mailboxes", v.MailboxViewSet, basename="email-mailboxes")
urlpatterns = [
    path("email/folders/<str:folder>", v.FolderView.as_view()),
    path("email/conversations/<uuid:cid>", v.ConversationView.as_view()),
    path("email/compose", v.ComposeView.as_view()),
    path("email/attachments/<uuid:attachment_id>", v.AttachmentView.as_view()),
    path("email/report", v.EmailReportView.as_view()),
    path("email/mailboxes/<uuid:mailbox_id>/sync", v.SyncNowView.as_view()),
    path("webhooks/email/<uuid:mailbox_id>/<str:provider>/inbound", InboundEmailWebhook.as_view()),
    path("webhooks/email/<uuid:mailbox_id>/<str:provider>/events", DeliveryEventWebhook.as_view()),
] + r.urls
