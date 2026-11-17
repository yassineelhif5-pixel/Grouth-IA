from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v

r = SimpleRouter(trailing_slash=False)
r.register("whatsapp/accounts", v.AccountViewSet, basename="wa-accounts")
r.register("whatsapp/templates", v.TemplateViewSet, basename="wa-templates")
r.register("whatsapp/contacts", v.ContactViewSet, basename="wa-contacts")
urlpatterns = [path("whatsapp/conversations", v.ConversationsView.as_view()), path("whatsapp/conversations/<uuid:cid>", v.ConversationView.as_view()),
               path("webhooks/whatsapp/<uuid:account_id>", v.WhatsAppWebhook.as_view())] + r.urls
