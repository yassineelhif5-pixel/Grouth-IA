"""Growth Intelligence Engine — OBSERVE → UNDERSTAND → DETECT → PRIORITIZE → PLAN → APPROVE → EXECUTE → MEASURE → LEARN → OPTIMIZE.

Recommendations are produced by explicit, versioned rules over the tenant's own data (never mixed across tenants):
each carries its sources, justification, confidence, impact, difficulty, risks and actions. Facts and hypotheses are
labelled; outcomes of accepted recommendations are measured against the baseline captured at detection time."""
from __future__ import annotations

import json

from django.db import transaction

from apps.audit.services import record_audit
from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError

METRICS = {
    "seo_score": "SELECT score FROM public.seo_audits WHERE tenant_id = %s AND status = 'succeeded' ORDER BY completed_at DESC LIMIT 1",
    "seo_score_prev": "SELECT score FROM public.seo_audits WHERE tenant_id = %s AND status = 'succeeded' ORDER BY completed_at DESC OFFSET 1 LIMIT 1",
    "critical_issues": """SELECT count(*) FROM public.seo_issues i WHERE i.tenant_id = %s AND i.severity IN ('critical','high') AND i.status = 'open'
                           AND i.audit_id = (SELECT id FROM public.seo_audits WHERE tenant_id = i.tenant_id AND status = 'succeeded' ORDER BY completed_at DESC LIMIT 1)""",
    "geo_visibility": "SELECT visibility_score FROM public.ai_visibility_snapshots WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 1",
    "contents_30d": "SELECT count(*) FROM public.generated_contents WHERE tenant_id = %s AND created_at > now() - interval '30 days' AND deleted_at IS NULL",
    "published_30d": "SELECT count(*) FROM public.content_publications WHERE tenant_id = %s AND status = 'published' AND created_at > now() - interval '30 days'",
    "new_opportunities_30d": "SELECT count(*) FROM public.opportunity_scores WHERE tenant_id = %s AND created_at > now() - interval '30 days'",
    "emails_sent_30d": "SELECT count(*) FROM public.email_messages WHERE tenant_id = %s AND direction = 'outbound' AND status NOT IN ('draft','failed','queued') AND created_at > now() - interval '30 days'",
    "replies_30d": "SELECT count(*) FROM public.email_messages WHERE tenant_id = %s AND direction = 'inbound' AND created_at > now() - interval '30 days'",
    "bounces_30d": "SELECT count(*) FROM public.email_messages WHERE tenant_id = %s AND status = 'bounced' AND created_at > now() - interval '30 days'",
    "stale_prospects": """SELECT count(*) FROM public.prospects WHERE tenant_id = %s AND deleted_at IS NULL AND status IN ('interested','demo_requested','negotiation','proposal_sent')
                           AND coalesce(last_activity_at, created_at) < now() - interval '7 days'""",
    "unanswered_hot": """SELECT count(*) FROM public.email_conversations c WHERE c.tenant_id = %s AND c.is_unread AND c.labels && ARRAY['interested','demo_requested']""",
    "customers": "SELECT count(*) FROM public.prospects WHERE tenant_id = %s AND status = 'customer' AND deleted_at IS NULL",
    "ai_cost_30d": "SELECT sum(cost_cents) FROM public.ai_execution_logs WHERE tenant_id = %s AND created_at > now() - interval '30 days'",
    "failed_runs_7d": "SELECT count(*) FROM public.scheduler_execution_runs WHERE tenant_id = %s AND status = 'failed' AND created_at > now() - interval '7 days'",
}


def observe() -> dict:
    tid = get_context().tenant_id
    out = {}
    for k, q in METRICS.items():
        v = fetch_one(q, [tid])
        out[k] = float(v[0]) if v and v[0] is not None else None
    fetch_one("INSERT INTO public.growth_intelligence_snapshots (tenant_id, data) VALUES (%s,%s::jsonb) RETURNING id", [tid, json.dumps(out)])
    return out


RULES = [
    # code, condition(m), title, justification(m), confidence, impact, difficulty, risks, actions, metric to improve, direction
    ("seo_drop", lambda m: m["seo_score"] is not None and m["seo_score_prev"] is not None and m["seo_score"] < m["seo_score_prev"] - 5,
     "Le score SEO a baissé", lambda m: f"Score {m['seo_score']} contre {m['seo_score_prev']} à l'audit précédent.", 0.9, "high", "medium",
     ["Régressions techniques non détectées"], ["Comparer les deux derniers audits", "Traiter les nouveaux problèmes critiques"], "seo_score", "up"),
    ("seo_critical", lambda m: (m["critical_issues"] or 0) > 0, "Des problèmes SEO critiques restent ouverts",
     lambda m: f"{int(m['critical_issues'])} problèmes critiques/élevés dans le dernier audit.", 0.95, "high", "low",
     [], ["Ouvrir les recommandations SEO prioritaires", "Planifier un nouvel audit après correction"], "critical_issues", "down"),
    ("geo_low", lambda m: m["geo_visibility"] is not None and m["geo_visibility"] < 30, "Faible visibilité dans les moteurs IA",
     lambda m: f"La marque apparaît dans {m['geo_visibility']} % des réponses observées.", 0.7, "high", "medium",
     ["Mesure basée sur un échantillon de requêtes"], ["Créer des contenus de référence pour les requêtes sans mention", "Ajouter FAQ et données structurées"],
     "geo_visibility", "up"),
    ("geo_unmeasured", lambda m: m["geo_visibility"] is None, "Visibilité GEO non mesurée",
     lambda m: "Aucune observation GEO n'est disponible.", 1.0, "medium", "low", [], ["Créer des requêtes GEO et les exécuter"], None, None),
    ("content_low", lambda m: (m["contents_30d"] or 0) < 2, "Production de contenu insuffisante",
     lambda m: f"{int(m['contents_30d'] or 0)} contenus créés sur 30 jours.", 0.8, "medium", "medium", [],
     ["Programmer une génération d'articles sur les opportunités mots-clés"], "contents_30d", "up"),
    ("hot_unanswered", lambda m: (m["unanswered_hot"] or 0) > 0, "Réponses chaudes non traitées",
     lambda m: f"{int(m['unanswered_hot'])} conversations intéressées ou demandes de démo non lues.", 0.95, "high", "low",
     ["Perte d'opportunité commerciale"], ["Traiter les conversations dans l'Email Center", "Affecter un commercial"], "unanswered_hot", "down"),
    ("stale_pipeline", lambda m: (m["stale_prospects"] or 0) > 0, "Prospects avancés sans activité",
     lambda m: f"{int(m['stale_prospects'])} prospects avancés sans interaction depuis 7 jours.", 0.9, "medium", "low", [],
     ["Programmer une relance CRM", "Préparer des réponses avec THOR"], "stale_prospects", "down"),
    ("bounce_high", lambda m: (m["emails_sent_30d"] or 0) >= 20 and (m["bounces_30d"] or 0) / m["emails_sent_30d"] > 0.05,
     "Taux de rebond élevé", lambda m: f"{int(m['bounces_30d'])} rebonds pour {int(m['emails_sent_30d'])} envois (30 j).", 0.9, "high", "medium",
     ["Dégradation de la réputation d'envoi"], ["Nettoyer les listes", "Vérifier SPF/DKIM/DMARC"], "bounces_30d", "down"),
    ("scheduler_failures", lambda m: (m["failed_runs_7d"] or 0) > 0, "Programmations en échec",
     lambda m: f"{int(m['failed_runs_7d'])} exécutions échouées sur 7 jours.", 1.0, "medium", "low", [], ["Consulter l'historique du Scheduler"], "failed_runs_7d", "down"),
]


def run_cycle() -> dict:
    tid = get_context().tenant_id
    m = observe()
    created = 0
    with transaction.atomic():
        for code, cond, title, just, conf, impact, diff, risks, actions, metric, direction in RULES:
            try:
                hit = cond(m)
            except (TypeError, ZeroDivisionError):
                hit = False
            if not hit:
                continue
            key = f"{code}"
            if fetch_one("SELECT 1 FROM public.growth_recommendations WHERE tenant_id = %s AND dedup_key = %s AND status IN ('open','accepted') AND deleted_at IS NULL", [tid, key]):
                continue
            prio = {"high": 1, "medium": 2, "low": 3}[impact] + (0 if diff == "low" else 1)
            sources = [{"metric": k, "value": m[k]} for k in METRICS if k in (metric, f"{metric}_prev") or (metric is None and k.startswith("geo"))]
            fetch_one("""INSERT INTO public.growth_recommendations (tenant_id, title, body, priority, status, rule_code, dedup_key, sources, justification,
                           confidence, impact, difficulty, risks, actions, nature)
                         VALUES (%s,%s,%s,%s,'open',%s,%s,%s::jsonb,%s,%s,%s,%s,%s::jsonb,%s::jsonb,'recommendation') RETURNING id""",
                      [tid, title, just(m), prio, code, key, json.dumps({"baseline": m.get(metric) if metric else None, "metric": metric, "direction": direction,
                                                                          "observations": sources}), just(m), conf, impact, diff, json.dumps(risks), json.dumps(actions)])
            fetch_one("""INSERT INTO public.growth_intelligence_insights (tenant_id, title, body, confidence, rule_code, sources, nature)
                         VALUES (%s,%s,%s,%s,%s,%s::jsonb,'fact') RETURNING id""", [tid, title, just(m), conf, code, json.dumps(sources)])
            created += 1
    learned = measure()
    record_audit("intelligence.cycle", "intelligence", after={"recommendations": created, "learned": learned})
    return {"metrics": m, "new_recommendations": created, "outcomes_measured": learned}


def decide(rec_id: str, accept: bool, comment: str) -> None:
    tid = get_context().tenant_id
    if not fetch_one("SELECT 1 FROM public.growth_recommendations WHERE id = %s AND tenant_id = %s AND status = 'open'", [rec_id, tid]):
        raise BusinessError("recommendation not open", "invalid_state", status_code=409)
    with transaction.atomic():
        fetch_one("UPDATE public.growth_recommendations SET status = %s WHERE id = %s RETURNING 1", ["accepted" if accept else "rejected", rec_id])
        fetch_one("INSERT INTO public.growth_recommendation_feedback (tenant_id, recommendation_id, user_id, rating, comment) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                  [tid, rec_id, get_context().user_id, 1 if accept else -1, comment])
        fetch_one("INSERT INTO public.growth_decision_logs (tenant_id, decision, rationale, decided_by, inputs) VALUES (%s,%s,%s,%s,%s::jsonb) RETURNING id",
                  [tid, f"{'accept' if accept else 'reject'} recommendation {rec_id}", comment, get_context().user_id, json.dumps({"recommendation_id": rec_id})])
        record_audit("intelligence.recommendation_decided", "intelligence", entity_type="growth_recommendations", entity_id=rec_id, after={"accepted": accept})


def measure() -> int:
    """LEARN: for accepted recommendations older than 7 days, compare the metric to its baseline."""
    tid = get_context().tenant_id
    n = 0
    for r in fetch_all_dict("""SELECT id, sources FROM public.growth_recommendations WHERE tenant_id = %s AND status = 'accepted'
                                AND updated_at < now() - interval '7 days' AND deleted_at IS NULL""", [tid]):
        src = r["sources"] or {}
        metric, base, direction = src.get("metric"), src.get("baseline"), src.get("direction")
        if not metric or base is None:
            continue
        cur = fetch_one(METRICS[metric], [tid])
        cur = float(cur[0]) if cur and cur[0] is not None else None
        if cur is None:
            continue
        improved = cur > base if direction == "up" else cur < base
        fetch_one("INSERT INTO public.growth_learning_events (tenant_id, source, lesson, data) VALUES (%s,'recommendation_outcome',%s,%s::jsonb) RETURNING id",
                  [tid, f"{metric}: {base} → {cur} ({'improved' if improved else 'not improved'})", json.dumps({"recommendation_id": str(r["id"]), "improved": improved})])
        fetch_one("UPDATE public.growth_recommendations SET status = 'done' WHERE id = %s RETURNING 1", [r["id"]])
        n += 1
    return n
