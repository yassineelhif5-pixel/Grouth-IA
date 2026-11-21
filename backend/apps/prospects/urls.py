from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v

r = SimpleRouter(trailing_slash=False)
for prefix, vs in [("prospects/projects", v.ProjectViewSet), ("prospects/companies", v.CompanyViewSet), ("prospects/contacts", v.ContactViewSet),
                   ("prospects/segments", v.SegmentViewSet), ("prospects/templates", v.TemplateViewSet), ("prospects/sequences", v.SequenceViewSet),
                   ("prospects/suppressions", v.SuppressionViewSet), ("prospects/items", v.ProspectViewSet), ("campaigns", v.CampaignViewSet),
                   ("crm/stages", v.StageViewSet), ("crm/opportunities", v.OpportunityViewSet), ("crm/tasks", v.TaskViewSet),
                   ("crm/meetings", v.MeetingViewSet), ("crm/activities", v.ActivityViewSet)]:
    r.register(prefix, vs, basename=prefix.replace("/", "-"))
urlpatterns = [
    path("crm/pipeline", v.PipelineView.as_view()),
    # prospect hunting
    path("prospects/hunt/keywords", v.KeywordScanView.as_view()),
    path("prospects/hunt/companies", v.CompanySearchView.as_view()),
    path("prospects/hunt/companies/add", v.CompanyAddView.as_view()),
    path("prospects/hunt/board", v.HuntBoardView.as_view()),
    path("prospects/hunt/<uuid:prospect_id>/<str:op>", v.ProspectHuntActionView.as_view()),
    path("public/prospects/go/<str:token>", v.TrialLinkView.as_view()),
    path("public/prospects/unsubscribe/<str:token>", v.UnsubscribeView.as_view()),
] + r.urls
