from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views as v

r = SimpleRouter(trailing_slash=False)
r.register("seo/projects", v.SeoProjectViewSet, basename="seo-projects")
r.register("seo/audits", v.SeoAuditViewSet, basename="seo-audits")
r.register("seo/issues", v.SeoIssueViewSet, basename="seo-issues")
r.register("seo/recommendations", v.SeoRecommendationViewSet, basename="seo-recommendations")
r.register("seo/keywords", v.SeoKeywordViewSet, basename="seo-keywords")
r.register("seo/keyword-groups", v.KeywordGroupViewSet, basename="seo-keyword-groups")
r.register("seo/backlinks", v.BacklinkViewSet, basename="seo-backlinks")
urlpatterns = [path("seo/rankings", v.RankingsView.as_view())] + r.urls
