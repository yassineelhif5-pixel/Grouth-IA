from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v

r = SimpleRouter(trailing_slash=False)
r.register("opportunities/projects", v.HuntProjectViewSet, basename="opp-projects")
r.register("social-hunter/configs", v.ListeningViewSet, basename="listening-configs")
r.register("social-hunter/signals", v.SignalViewSet, basename="social-signals")
urlpatterns = [path("opportunities", v.OpportunityBoardView.as_view()),
               path("opportunities/<uuid:opp_id>/evidence", v.OpportunityEvidenceView.as_view())] + r.urls
