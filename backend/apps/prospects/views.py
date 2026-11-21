import json

from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.crud import crud
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.views import GrowthAPIView
from apps.core.webhooks import PublicWebhookView

from . import hunt
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


# ───────────────────────────── Prospect hunting ─────────────────────────────
class _HuntBase(GrowthAPIView):
    required_module = "prospects"
    permission_map = {"GET": "prospects.read", "POST": "prospects.write"}


class KeywordScanView(_HuntBase):
    def post(self, request):
        return Response(hunt.scan_keywords(str(request.data.get("url") or ""), int(request.data.get("max_pages") or 5)))


class CompanySearchView(_HuntBase):
    def get(self, request):
        return Response(hunt.search_companies(request.query_params.get("q", ""), request.query_params.get("category"),
                                              int(request.query_params.get("page") or 1)))


class _AddCompanies(serializers.Serializer):
    companies = serializers.ListField(child=serializers.DictField(), min_length=1, max_length=50)
    product_id = serializers.UUIDField(required=False, allow_null=True)


class CompanyAddView(_HuntBase):
    def post(self, request):
        ser = _AddCompanies(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        return Response(hunt.add_companies(d["companies"], str(d["product_id"]) if d.get("product_id") else None), status=201)


class HuntBoardView(_HuntBase):
    """Prospect cards: company, contacts, score and its reasons, e-mail follow-up summary — best first."""

    def get(self, request):
        tid = request.tenant.tenant_id
        rows = fetch_all_dict("""
            SELECT p.id, p.status, p.score, p.need_detected, p.source_detail, p.created_at, p.last_activity_at,
                   c.name AS company, c.domain, c.industry, c.size_employees, c.data AS company_data,
                   (SELECT json_agg(json_build_object('id', pc.id, 'first_name', pc.first_name, 'last_name', pc.last_name, 'email', pc.email,
                                                      'job_title', pc.job_title, 'consent_status', pc.consent_status) ORDER BY pc.created_at)
                      FROM public.prospect_contacts pc WHERE pc.prospect_id = p.id AND pc.deleted_at IS NULL) AS contacts,
                   (SELECT max(m.sent_at) FROM public.email_messages m WHERE m.prospect_id = p.id AND m.direction = 'outbound') AS last_sent_at,
                   (SELECT count(*) FROM public.email_messages m WHERE m.prospect_id = p.id AND m.direction = 'outbound' AND m.status NOT IN ('failed','draft')) AS sent_count,
                   (SELECT max(m.received_at) FROM public.email_messages m WHERE m.prospect_id = p.id AND m.direction = 'inbound') AS last_reply_at,
                   EXISTS (SELECT 1 FROM public.crm_activities a WHERE a.prospect_id = p.id AND a.entity_ref->>'event' = 'trial_link_clicked') AS trial_clicked
              FROM public.prospects p LEFT JOIN public.prospect_companies c ON c.id = p.company_id
             WHERE p.tenant_id = %s AND p.deleted_at IS NULL AND (%s::uuid IS NULL OR p.product_id = %s::uuid)
             ORDER BY p.score DESC NULLS LAST, p.created_at DESC LIMIT 200""",
            [tid, request.query_params.get("product") or None, request.query_params.get("product") or None])
        return Response(rows)


class ProspectHuntActionView(_HuntBase):
    def post(self, request, prospect_id, op):
        if not fetch_one("SELECT 1 FROM public.prospects WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL",
                         [str(prospect_id), request.tenant.tenant_id]):
            return Response({"error": {"code": "not_found", "message": "prospect not found"}}, status=404)
        pid = str(prospect_id)
        if op == "site-contacts":
            return Response(hunt.find_site_contacts(pid, request.data.get("domain")))
        if op == "enrich":
            return Response(hunt.enrich_with_provider(pid))
        if op == "score":
            return Response(hunt.score_prospect(pid))
        if op == "draft":
            return Response(hunt.draft_email(pid, request.data.get("contact_id")))
        if op == "send":
            for k in ("mailbox_id", "to", "subject", "body"):
                if not request.data.get(k):
                    return Response({"error": {"code": "invalid", "message": f"{k} is required", "details": {k: ["required"]}}}, status=400)
            return Response(hunt.send(pid, str(request.data["mailbox_id"]), request.data["to"], request.data["subject"], request.data["body"]))
        return Response({"error": {"code": "not_found", "message": "unknown action"}}, status=404)

    def get(self, request, prospect_id, op):
        if op != "history":
            return Response({"error": {"code": "not_found", "message": "unknown action"}}, status=404)
        if not fetch_one("SELECT 1 FROM public.prospects WHERE id = %s AND tenant_id = %s", [str(prospect_id), request.tenant.tenant_id]):
            return Response({"error": {"code": "not_found", "message": "prospect not found"}}, status=404)
        return Response(hunt.history(str(prospect_id)))


class TrialLinkView(PublicWebhookView):
    """Tracked trial link from a prospecting e-mail: records the click (contact request signal) then redirects to sign-up."""

    def get(self, request, token):
        d = hunt.read_token(token, "go")
        self.platform_scope(request)
        self.tenant_scope(request, d["t"])
        if fetch_one("SELECT 1 FROM public.prospects WHERE id = %s AND tenant_id = %s", [d["p"], d["t"]]):
            fetch_one("""INSERT INTO public.crm_activities (tenant_id, prospect_id, activity_type, summary, channel, actor_type, entity_ref)
                         VALUES (%s,%s,'note','Lien d''essai cliqué depuis l''e-mail de prospection','email','system',%s::jsonb) RETURNING id""",
                      [d["t"], d["p"], json.dumps({"event": "trial_link_clicked", "contact_id": d.get("c")})])
            fetch_one("""UPDATE public.prospects SET status = CASE WHEN status IN ('new','new_lead','enriched','qualified','contacted') THEN 'interested'
                          ELSE status END, last_activity_at = now() WHERE id = %s RETURNING 1""", [d["p"]])
            from apps.notifications.service import notify
            notify("prospect.qualified", {"name": "Un prospect a cliqué sur le lien d'essai", "score": ""}, permission="prospects.read",
                   tenant_id=d["t"])
        return HttpResponseRedirect(f"{settings.GROWTH['FRONTEND_URL'].rstrip('/')}/signup")


class UnsubscribeView(PublicWebhookView):
    """One-click unsubscribe: suppression list + contact opted out + prospect status, recorded in the history."""

    def get(self, request, token):
        d = hunt.read_token(token, "unsub")
        self.platform_scope(request)
        self.tenant_scope(request, d["t"])
        emails = [r[0] for r in [fetch_one("SELECT email FROM public.prospect_contacts WHERE id = %s AND tenant_id = %s", [d["c"], d["t"]])]
                  if r and r[0]] if d.get("c") else []
        for e in emails:
            if not fetch_one("SELECT 1 FROM public.prospect_suppression_lists WHERE tenant_id = %s AND lower(email) = lower(%s) AND deleted_at IS NULL",
                             [d["t"], e]):
                fetch_one("INSERT INTO public.prospect_suppression_lists (tenant_id, email, reason) VALUES (%s,%s,'unsubscribed') RETURNING id", [d["t"], e])
            fetch_one("UPDATE public.prospect_contacts SET consent_status = 'opted_out' WHERE tenant_id = %s AND lower(email) = lower(%s) RETURNING 1",
                      [d["t"], e])
        fetch_one("UPDATE public.prospects SET status = 'unsubscribed' WHERE id = %s AND tenant_id = %s RETURNING 1", [d["p"], d["t"]])
        fetch_one("""INSERT INTO public.crm_activities (tenant_id, prospect_id, activity_type, summary, channel, actor_type, entity_ref)
                     VALUES (%s,%s,'note','Désinscription demandée par le contact','email','system',%s::jsonb) RETURNING id""",
                  [d["t"], d["p"], json.dumps({"event": "unsubscribed", "contact_id": d.get("c")})])
        return HttpResponse("<!doctype html><meta charset='utf-8'><title>Désinscription</title><p style='font-family:sans-serif'>"
                            "Votre désinscription est enregistrée : vous ne recevrez plus nos messages.</p>")
