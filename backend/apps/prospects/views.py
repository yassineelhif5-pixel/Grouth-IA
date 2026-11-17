from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.crud import crud
from apps.core.db import fetch_all_dict
from apps.core.views import GrowthAPIView

from . import models as m
from . import services as s

ProjectViewSet = crud(m.ProspectProject, module="prospects", perm="prospects", filters=["product", "status"])
CompanyViewSet = crud(m.ProspectCompany, module="prospects", perm="prospects", search=["name", "domain"], filters=["industry", "country_code"])
ContactViewSet = crud(m.ProspectContact, module="prospects", perm="prospects", search=["email", "last_name"], filters=["prospect", "consent_status"])
SegmentViewSet = crud(m.ProspectSegment, module="prospects", perm="prospects", filters=["project"])
TemplateViewSet = crud(m.ProspectTemplate, module="prospects", perm="campaigns", write="manage", filters=["channel"])
SequenceViewSet = crud(m.ProspectCampaignSequence, module="prospects", perm="campaigns", write="manage", filters=["campaign"], ordering=["step"])
SuppressionViewSet = crud(m.ProspectSuppressionList, module="prospects", perm="prospects", search=["email"])
_P = crud(m.Prospect, module="prospects", perm="prospects", filters=["project", "company", "status", "owner_user_id", "product"], quota="prospects.max",
          ordering=["-score", "-created_at"])


class ProspectViewSet(_P):
    @action(detail=True, methods=["post"])
    def qualify(self, request, pk=None):
        self.get_object()
        return Response(s.qualify(str(pk)))

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        self.get_object()
        s.assign(str(pk), request.data["user_id"])
        return Response({"status": "assigned"})

    @action(detail=False, methods=["post"], url_path="import")
    def import_csv(self, request):
        return Response(s.import_csv(request.data.get("project_id"), request.data["csv"], request.data.get("source", "CSV import")), status=201)

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        self.get_object()
        tid = request.tenant.tenant_id
        return Response(fetch_all_dict("""
            SELECT * FROM (
              SELECT 'activity' AS kind, a.created_at AS at, a.activity_type AS type, a.summary AS text, a.actor_type AS actor, a.entity_ref AS ref
                FROM public.crm_activities a WHERE a.prospect_id = %(p)s AND a.tenant_id = %(t)s
              UNION ALL
              SELECT 'email', coalesce(m.received_at, m.sent_at, m.created_at), m.direction, m.subject, m.from_email, json_build_object('id', m.id, 'status', m.status, 'classification', m.classification)::jsonb
                FROM public.email_messages m WHERE m.prospect_id = %(p)s AND m.tenant_id = %(t)s
              UNION ALL
              SELECT 'whatsapp', w.created_at, w.direction, left(w.body, 300), w.status, json_build_object('id', w.id)::jsonb
                FROM public.whatsapp_messages w JOIN public.whatsapp_conversations c ON c.id = w.conversation_id JOIN public.whatsapp_contacts k ON k.id = c.contact_id
                JOIN public.prospect_contacts pc ON pc.id = k.prospect_contact_id WHERE pc.prospect_id = %(p)s AND w.tenant_id = %(t)s
              UNION ALL
              SELECT 'change', h.created_at, h.operation, array_to_string(h.changed_fields, ', '), h.actor_type, json_build_object('version', h.version_number, 'status', h.current_data->>'status')::jsonb
                FROM public.entity_history h WHERE h.entity_type = 'prospects' AND h.entity_id = %(p)s AND h.tenant_id = %(t)s
            ) x ORDER BY at DESC LIMIT 500""", {"p": str(pk), "t": tid}))


_C = crud(m.ProspectCampaign, module="prospects", perm="campaigns", write="manage", filters=["project", "status", "channel"])


class CampaignViewSet(_C):
    @action(detail=True, methods=["post"])
    def launch(self, request, pk=None):
        self.get_object()
        return Response(s.launch_campaign(str(pk)))

    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        from apps.core.services import audited_update
        audited_update(self.get_object(), {"status": "paused"}, action="campaign.paused", module="prospects")
        return Response({"status": "paused"})

    @action(detail=True, methods=["post"])
    def process(self, request, pk=None):
        self.get_object()
        return Response(s.process_campaign(str(pk)))


StageViewSet = crud(m.CrmPipelineStage, module="crm", perm="crm", ordering=["position"])
OpportunityViewSet = crud(m.CrmOpportunity, module="crm", perm="crm", filters=["stage", "prospect", "owner_user_id", "product"])
TaskViewSet = crud(m.CrmTask, module="crm", perm="crm", filters=["assigned_to", "status", "opportunity"], ordering=["due_at"])
MeetingViewSet = crud(m.CrmMeeting, module="crm", perm="crm", filters=["opportunity"], ordering=["starts_at"])
ActivityViewSet = crud(m.CrmActivity, module="crm", perm="crm", filters=["prospect", "opportunity", "activity_type"])

DEFAULT_STAGES = [("New Lead", 10), ("Contacted", 20), ("Qualified", 30), ("Interested", 40), ("Demo Requested", 50), ("Meeting Scheduled", 60),
                  ("Proposal Sent", 70), ("Negotiation", 80), ("Customer", 100), ("Lost", 0)]


class PipelineView(GrowthAPIView):
    permission_map = {"GET": "crm.read", "POST": "crm.write"}
    required_module = "crm"

    def get(self, request):
        tid = request.tenant.tenant_id
        return Response({
            "prospects_by_status": fetch_all_dict("SELECT status, count(*) AS n FROM public.prospects WHERE tenant_id = %s AND deleted_at IS NULL GROUP BY status", [tid]),
            "stages": fetch_all_dict("""SELECT s.id, s.name, s.position, s.probability_pct, s.is_won, s.is_lost, count(o.id) AS opportunities, coalesce(sum(o.amount_cents),0) AS amount_cents
                                          FROM public.crm_pipeline_stages s LEFT JOIN public.crm_opportunities o ON o.stage_id = s.id AND o.deleted_at IS NULL
                                         WHERE s.tenant_id = %s AND s.deleted_at IS NULL GROUP BY s.id ORDER BY s.position""", [tid])})

    def post(self, request):
        """Initialise the default pipeline (idempotent)."""
        from apps.core.db import fetch_one
        tid = request.tenant.tenant_id
        if not fetch_one("SELECT 1 FROM public.crm_pipeline_stages WHERE tenant_id = %s AND deleted_at IS NULL", [tid]):
            for i, (name, prob) in enumerate(DEFAULT_STAGES):
                fetch_one("""INSERT INTO public.crm_pipeline_stages (tenant_id, name, position, probability_pct, is_won, is_lost) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                          [tid, name, i, prob, name == "Customer", name == "Lost"])
        return self.get(request)
