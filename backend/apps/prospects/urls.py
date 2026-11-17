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
urlpatterns = [path("crm/pipeline", v.PipelineView.as_view())] + r.urls
