"""Blog autopilot: articles written by the AI on a chosen theme and published automatically on the tenant's CMS
(WordPress, Ghost or any REST CMS connected in Connectors), planned through a conversation with an assistant,
confirmed explicitly, then executed by the Multi-Scheduler with a full history (plan, runs, published links).

Flow: GET themes → POST chat (assistant fills the plan, works without AI as a guided dialogue) → POST confirm
(creates a scheduler of category 'articles' with autopilot params; confirmation recorded in the activity history)
→ each run: new article (no repeated title) → publication as configured (publish now / CMS draft / approval first).
"""
from __future__ import annotations

import json
import re
from base64 import b64encode

from django.db import transaction

from apps.audit.services import record_activity, record_audit
from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.integrations.gateway import http

CMS_PROVIDERS = ("wordpress", "ghost", "rest_cms")
DAYS = {"lundi": 1, "mardi": 2, "mercredi": 3, "jeudi": 4, "vendredi": 5, "samedi": 6, "dimanche": 0}
DAY_NAMES = {v: k for k, v in DAYS.items()}
LENGTHS = {"court": 700, "moyen": 1200, "long": 2000}
PUBLISH_MODES = {"publish": "publiés directement sur le site", "draft": "envoyés en brouillon sur le site (vous publiez vous-même)",
                 "approval": "soumis à votre validation dans Growth IA avant publication"}
QUESTIONS = [
    ("frequency", "À quel rythme voulez-vous publier ? (ex. « 1 article par semaine », « 2 par semaine », « 1 par jour »)"),
    ("day_time", "Quel jour et à quelle heure ? (ex. « le mardi à 9h »)"),
    ("length", "Quelle longueur d'article : court (~700 mots), moyen (~1 200 mots) ou long (~2 000 mots) ?"),
    ("tone", "Quel ton souhaitez-vous ? (ex. expert, pédagogique, convivial)"),
    ("publish_mode", "Une fois rédigé, l'article doit-il être publié directement, envoyé en brouillon sur votre site, ou validé d'abord par vous dans Growth IA ?"),
]


# ───────────────────────────── connector & themes ─────────────────────────────
def cms_accounts() -> list[dict]:
    return fetch_all_dict("""SELECT a.id, p.code AS provider, a.display_name, a.status, a.settings->>'site_url' AS site_url
                               FROM public.tenant_connector_accounts a JOIN public.connector_providers p ON p.id = a.provider_id
                              WHERE a.tenant_id = %s AND a.deleted_at IS NULL AND a.status <> 'revoked' AND p.code = ANY(%s)
                              ORDER BY a.created_at""", [get_context().tenant_id, list(CMS_PROVIDERS)])


def _account(account_id: str) -> dict:
    acc = next((a for a in cms_accounts() if str(a["id"]) == str(account_id)), None)
    if not acc:
        raise BusinessError("Connecteur de publication introuvable : connectez WordPress, Ghost ou votre CMS dans Connecteurs",
                            "connector_not_found", status_code=404)
    return acc


def wordpress_categories(account_id: str) -> list[dict]:
    from apps.integrations.gateway import get_credentials
    acc = _account(account_id)
    if acc["provider"] != "wordpress":
        return []
    cred = get_credentials(acc["id"])
    auth = {"Authorization": "Basic " + b64encode(f"{cred['username']}:{cred['application_password']}".encode()).decode()}
    rows = http("GET", f"{(acc['site_url'] or '').rstrip('/')}/wp-json/wp/v2/categories", provider="wordpress", operation="categories",
                account_id=acc["id"], headers=auth, params={"per_page": 100, "hide_empty": "false"}).json()
    return [{"id": r["id"], "name": r.get("name", "")} for r in rows if isinstance(r, dict)]


def suggest_themes(product_id: str | None) -> dict:
    """Editorial themes: from the product, its SEO keywords and visibility recommendations; refined by the AI when configured."""
    tid = get_context().tenant_id
    prod = fetch_one("SELECT name, coalesce(description,'') FROM public.products WHERE id = %s AND tenant_id = %s", [product_id, tid]) if product_id else None
    kws = [r["keyword"] for r in fetch_all_dict("""SELECT DISTINCT k.keyword FROM public.seo_keywords k JOIN public.seo_projects sp ON sp.id = k.project_id
                                                   WHERE k.tenant_id = %s AND (%s::uuid IS NULL OR sp.product_id = %s::uuid)
                                                     AND k.deleted_at IS NULL LIMIT 15""", [tid, product_id, product_id])]
    name = prod[0] if prod else "votre offre"
    from apps.ai_providers.gateway import AINotConfigured, complete, wrap_untrusted
    try:
        res = complete("content.themes", [{"role": "user", "content": wrap_untrusted("product", json.dumps(
            {"produit": name, "description": prod[1][:1500] if prod else "", "mots_cles": kws}, ensure_ascii=False))}], untrusted=True,
            max_tokens=700, temperature=0.6, product_id=product_id,
            system=("Propose 8 thèmes éditoriaux de blog B2B en français qui font remonter ce produit dans Google et dans les réponses des "
                    'assistants IA (ChatGPT, Perplexity, Gemini). JSON uniquement : [{"theme": "...", "why": "..."}]'))
        data = json.loads(res.text[res.text.find("["): res.text.rfind("]") + 1])
        return {"themes": [{"theme": str(d["theme"])[:160], "why": str(d.get("why", ""))[:300]} for d in data if d.get("theme")][:10], "method": "ai"}
    except (AINotConfigured, BusinessError, ValueError, KeyError, TypeError):  # AI is optional here: rules take over
        pass
    base = [f"Guide pratique : bien choisir {name}", f"{name} : cas d'usage et retours d'expérience", "Les tendances 2026 de votre secteur",
            f"Comparatif : {name} face aux alternatives", f"FAQ : tout savoir sur {name}", "Erreurs fréquentes à éviter et bonnes pratiques"]
    return {"themes": [{"theme": t, "why": "Format qui capte la recherche Google et les questions posées aux assistants IA"} for t in base]
            + [{"theme": f"Tout comprendre sur « {k} »", "why": "Mot-clé déjà suivi pour ce produit"} for k in kws[:4]], "method": "rules"}


# ───────────────────────────── conversation ─────────────────────────────
def parse_answer(text: str) -> dict:
    """Deterministic extraction of plan fields from a French sentence (works without any AI)."""
    t = (text or "").lower()
    out: dict = {}
    n = re.search(r"(\d+)\s*(?:article|post|publication|fois)?s?\s*(?:par|/|chaque)\s*(jour|semaine|mois)", t)
    if n:
        out["per_period"], out["frequency"] = max(1, min(int(n.group(1)), 7)), {"jour": "daily", "semaine": "weekly", "mois": "monthly"}[n.group(2)]
    elif re.search(r"quotidien|tous les jours|chaque jour|par jour", t):
        out["per_period"], out["frequency"] = 1, "daily"
    elif re.search(r"hebdo|par semaine|chaque semaine|toutes les semaines", t):
        out["per_period"], out["frequency"] = 1, "weekly"
    elif re.search(r"mensuel|par mois|chaque mois|tous les mois", t):
        out["per_period"], out["frequency"] = 1, "monthly"
    day = next((d for d in DAYS if re.search(rf"\b{d}s?\b", t)), None)
    if day:
        out["day"] = DAYS[day]
    h = re.search(r"\b([01]?\d|2[0-3])\s*(?:h|:)\s*([0-5]\d)?\b", t)
    if h:
        out["time"] = f"{int(h.group(1)):02d}:{h.group(2) or '00'}"
    words = re.search(r"(\d{3,4})\s*mots", t)
    if words:
        out["words"] = max(300, min(int(words.group(1)), 3500))
    else:
        size = next((k for k in LENGTHS if re.search(rf"\b{k}s?\b", t)), None)
        if size:
            out["words"] = LENGTHS[size]
    if re.search(r"brouillon", t):
        out["publish_mode"] = "draft"
    elif re.search(r"valid|relire|vérifi|approuv", t):
        out["publish_mode"] = "approval"
    elif re.search(r"direct|automatique|publie", t):
        out["publish_mode"] = "publish"
    tone = re.search(r"\b(expert|pédagogique|pedagogique|convivial|formel|professionnel|inspirant|technique|décontracté|chaleureux)\b", t)
    if tone:
        out["tone"] = tone.group(1)
    return out


def _missing(plan: dict) -> tuple[str, str] | None:
    have = {"frequency": plan.get("frequency") in ("daily", "weekly", "monthly"),
            "day_time": bool(plan.get("time")) and (plan.get("frequency") != "weekly" or plan.get("day") is not None),
            "length": bool(plan.get("words")), "tone": bool(plan.get("tone")), "publish_mode": plan.get("publish_mode") in PUBLISH_MODES}
    return next(((k, q) for k, q in QUESTIONS if not have[k]), None)


def summary(plan: dict) -> str:
    freq = {"daily": "par jour", "weekly": "par semaine", "monthly": "par mois"}.get(plan.get("frequency", ""), "")
    when = (f"le {DAY_NAMES.get(plan['day'], '')} " if plan.get("frequency") == "weekly" and "day" in plan else "") + f"à {plan.get('time', '09:00')}"
    return (f"{plan.get('per_period', 1)} article(s) {freq}, {when}, sur le thème « {plan.get('theme', '')} », d'environ "
            f"{plan.get('words', 1200)} mots, ton {plan.get('tone', 'expert')}. Les articles seront {PUBLISH_MODES.get(plan.get('publish_mode', ''), '')}"
            f"{(' sur ' + plan['site']) if plan.get('site') else ''}.")


def chat(message: str, plan: dict, history: list[dict]) -> dict:
    """Publication assistant: updates the plan from the user's message, asks the next missing question, then recaps for confirmation."""
    plan = {k: v for k, v in (plan or {}).items() if k in ("account_id", "product_id", "theme", "frequency", "per_period", "day", "time", "words",
                                                           "tone", "publish_mode", "category_ids", "site", "language")}
    plan.update(parse_answer(message))
    from apps.ai_providers.gateway import AINotConfigured, complete, wrap_untrusted
    source = "guided"
    try:  # the AI may extract what the rules missed; the deterministic parser stays authoritative for what it found
        res = complete("content.autopilot", [{"role": "user", "content": wrap_untrusted("message", message)}], untrusted=True, max_tokens=300,
                       temperature=0, system=("Extrais du message un plan de publication. JSON uniquement avec les clés présentes parmi : "
                                              '"frequency" (daily|weekly|monthly), "per_period" (entier), "day" (0=dimanche..6), "time" ("HH:MM"), '
                                              '"words" (entier), "tone" (texte court), "publish_mode" (publish|draft|approval).'))
        extra = json.loads(res.text[res.text.find("{"): res.text.rfind("}") + 1])
        plan.update({k: v for k, v in extra.items() if k not in plan and k in ("frequency", "per_period", "day", "time", "words", "tone", "publish_mode")})
        source = "ai"
    except (AINotConfigured, BusinessError, ValueError, KeyError, TypeError):  # AI is optional here: rules take over
        pass
    nxt = _missing(plan)
    if not plan.get("theme"):
        reply, ready = "Choisissez d'abord un thème dans la liste (ou écrivez le vôtre), puis répondez à mes questions.", False
    elif nxt:
        reply, ready = ("C'est noté. " if history else "Bonjour ! Je vais programmer la publication automatique de vos articles. ") + nxt[1], False
    else:
        reply, ready = f"Voici le programme que je vous propose : {summary(plan)} Confirmez-vous ?", True
    return {"reply": reply, "plan": plan, "ready": ready, "next_question": nxt[0] if nxt else None, "source": source,
            "summary": summary(plan) if ready else None}


# ───────────────────────────── confirmation & execution ─────────────────────────────
def confirm(plan: dict) -> dict:
    """Creates the publication scheduler from the confirmed plan; the confirmation is kept in the history."""
    from apps.licensing.services import check_quota
    from apps.scheduler.engine import next_run
    from apps.visibility.services import _content_project
    tid = get_context().tenant_id
    if _missing(plan) or not plan.get("theme") or not plan.get("product_id"):
        raise BusinessError("Le programme est incomplet : terminez la discussion avec l'assistant", "plan_incomplete")
    acc = _account(plan["account_id"])
    check_quota(tid, "scheduler.configurations")
    freq, per = plan["frequency"], int(plan.get("per_period", 1))
    time_ = plan.get("time", "09:00")
    if freq == "daily" and per > 1:
        ftype, fval = "every_x_hours", str(max(1, 24 // per))
    elif freq == "weekly":
        # scheduler weekly value = "<weekday 0=Monday> HH:MM"; several per week = evenly spaced
        ftype, fval = ("weekly", f"{(int(plan.get('day', 1)) - 1) % 7} {time_}") if per == 1 else ("every_x_hours", str(max(1, 168 // per)))
    elif freq == "monthly":
        ftype, fval = "monthly", f"1 {time_}"
    else:
        ftype, fval = "daily", time_
    product = fetch_one("SELECT name FROM public.products WHERE id = %s AND tenant_id = %s", [plan["product_id"], tid])
    if not product:
        raise BusinessError("product not found", "not_found", status_code=404)
    params = {"autopilot": True, "account_id": str(acc["id"]), "cms": acc["provider"], "site": acc["site_url"], "product_id": plan["product_id"],
              "content_project_id": _content_project(plan["product_id"], product[0]), "theme": plan["theme"], "keyword": plan["theme"][:200],
              "content_type": "article", "language": plan.get("language", "fr"), "words": int(plan.get("words", 1200)), "tone": plan.get("tone", "expert"),
              "publish_mode": plan["publish_mode"], "category_ids": [int(c) for c in plan.get("category_ids") or []][:5]}
    mode = "approval" if plan["publish_mode"] == "approval" else "automatic"
    name = f"Articles — {plan['theme']}"[:200]
    with transaction.atomic():
        sid = str(fetch_one("""INSERT INTO public.tenant_schedulers (tenant_id, product_id, name, description, timezone, status, category, frequency_type,
                                 frequency_value, params, mode, next_run_at)
                               VALUES (%s,%s,%s,%s,'Europe/Paris','active','articles',%s,%s,%s::jsonb,%s,%s) RETURNING id""",
                            [tid, plan["product_id"], name, summary({**plan, "site": acc["site_url"]}), ftype, fval, json.dumps(params), mode,
                             next_run(ftype, fval, "Europe/Paris")])[0])
        nxt = fetch_one("SELECT next_run_at FROM public.tenant_schedulers WHERE id = %s", [sid])[0]
        record_activity("content.autopilot_confirmed", "content", entity_type="tenant_schedulers", entity_id=sid, product_id=plan["product_id"],
                        description=f"Publication automatique confirmée : {summary({**plan, 'site': acc['site_url']})}", metadata=params)
    return {"scheduler_id": sid, "next_run_at": nxt, "summary": summary({**plan, "site": acc["site_url"]}),
            "confirmation": f"Programme confirmé. Premier article prévu le {nxt:%d/%m/%Y à %H:%M}." if nxt else "Programme confirmé."}


def run(p: dict) -> dict:
    """One scheduled occurrence: a new article on the theme (never a repeated title), then publication as configured."""
    from apps.content.services import generate, request_publication
    tid = get_context().tenant_id
    previous = [r["title"] for r in fetch_all_dict("""SELECT title FROM public.generated_contents WHERE tenant_id = %s AND project_id = %s
                                                       AND keyword = %s AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 30""",
                                                    [tid, p["content_project_id"], p["keyword"]])]
    cid = str(fetch_one("""INSERT INTO public.generated_contents (tenant_id, project_id, title, content_type, keyword, objective, product_id, language, status)
                           VALUES (%s,%s,%s,'article',%s,%s,%s,%s,'draft') RETURNING id""",
                        [tid, p["content_project_id"], f"Article — {p['theme']}"[:300], p["keyword"],
                         "Faire remonter le produit dans Google et dans les réponses des assistants IA", p["product_id"], p.get("language", "fr")])[0])
    brief = (f"Thème : {p['theme']}. Ton : {p.get('tone', 'expert')}. Longueur visée : environ {p.get('words', 1200)} mots. "
             "Commence par une ligne « # Titre accrocheur » (titre nouveau, différent de : " + "; ".join(previous[:15]) + "). "
             "Structure H2/H3, réponses directes aux questions, FAQ finale, sources citées ; ne jamais inventer de chiffre.")
    gen = generate(cid, "generate", brief)
    body = fetch_one("SELECT coalesce(body,'') FROM public.generated_contents WHERE id = %s", [cid])[0]
    m = re.match(r"\s*#\s+(.+)\n", body)
    if m:  # the AI's own title becomes the article title (removed from the body: the CMS shows the title itself)
        fetch_one("UPDATE public.generated_contents SET title = %s, body = %s WHERE id = %s RETURNING 1",
                  [m.group(1).strip()[:300], body[m.end():].lstrip(), cid])
    if p.get("publish_mode") == "approval":
        from apps.notifications.service import notify
        title = fetch_one("SELECT title FROM public.generated_contents WHERE id = %s", [cid])[0]
        notify("content.awaiting_approval", {"title": title}, permission="content.publish")
        return {**gen, "content_id": cid, "publication": "awaiting_approval"}
    fetch_one("UPDATE public.generated_contents SET status = 'approved' WHERE id = %s RETURNING 1", [cid])
    record_audit("content.auto_approved", "content", entity_type="generated_contents", entity_id=cid,
                 description="Approuvé automatiquement par le programme de publication confirmé", after={"publish_mode": p.get("publish_mode")})
    pub = request_publication(cid, p["account_id"], status="draft" if p.get("publish_mode") == "draft" else "publish",
                              category_ids=p.get("category_ids") or None, pre_approved=True)  # confirmed programme = prior approval
    return {**gen, "content_id": cid, "publication": pub}


def history(product_id: str | None = None) -> dict:
    """Confirmed programmes, their executions and every article published (link, date, status)."""
    tid = get_context().tenant_id
    plans = fetch_all_dict("""SELECT s.id, s.name, s.description, s.status, s.mode, s.next_run_at, s.last_run_at, s.last_status, s.params, s.created_at
                                FROM public.tenant_schedulers s WHERE s.tenant_id = %s AND s.category = 'articles' AND s.deleted_at IS NULL
                                 AND coalesce((s.params->>'autopilot')::boolean, false) AND (%s::uuid IS NULL OR s.product_id = %s::uuid)
                               ORDER BY s.created_at DESC""", [tid, product_id, product_id])
    articles = fetch_all_dict("""SELECT g.id, g.title, g.status AS content_status, g.seo_score, g.geo_score, g.created_at, p.status AS publication_status,
                                        p.external_url, p.published_at, p.error_message
                                   FROM public.generated_contents g
                                   LEFT JOIN LATERAL (SELECT status, external_url, published_at, error_message FROM public.content_publications cp
                                                       WHERE cp.content_id = g.id ORDER BY cp.created_at DESC LIMIT 1) p ON true
                                  WHERE g.tenant_id = %s AND g.deleted_at IS NULL AND g.project_id IN (
                                        SELECT (s.params->>'content_project_id')::uuid FROM public.tenant_schedulers s WHERE s.tenant_id = %s
                                           AND coalesce((s.params->>'autopilot')::boolean, false))
                                    AND (%s::uuid IS NULL OR g.product_id = %s::uuid)
                                  ORDER BY g.created_at DESC LIMIT 200""", [tid, tid, product_id, product_id])
    events = fetch_all_dict("""SELECT event_type, description, entity_id, created_at FROM public.activity_events WHERE tenant_id = %s
                                 AND event_type IN ('content.autopilot_confirmed', 'content.autopilot_paused', 'content.autopilot_resumed')
                               ORDER BY created_at DESC LIMIT 100""", [tid])
    return {"plans": plans, "articles": articles, "events": events}


def approve_and_publish(content_id: str) -> dict:
    """Programme in 'validation first' mode: the user validates the article, it is then published with the programme's settings."""
    from apps.content.services import request_publication
    tid = get_context().tenant_id
    row = fetch_one("""SELECT s.params FROM public.generated_contents g JOIN public.tenant_schedulers s ON s.tenant_id = g.tenant_id
                         AND (s.params->>'content_project_id')::uuid = g.project_id AND s.params->>'keyword' = g.keyword
                         AND coalesce((s.params->>'autopilot')::boolean, false) AND s.deleted_at IS NULL
                        WHERE g.id = %s AND g.tenant_id = %s ORDER BY s.created_at DESC LIMIT 1""", [content_id, tid])
    if not row:
        raise BusinessError("Cet article n'appartient à aucun programme de publication", "not_found", status_code=404)
    p = row[0]
    fetch_one("UPDATE public.generated_contents SET status = 'approved' WHERE id = %s AND status IN ('draft','in_review','approved') RETURNING 1",
              [content_id])
    record_audit("content.approved", "content", entity_type="generated_contents", entity_id=content_id, description="Validé avant publication automatique")
    return request_publication(content_id, p["account_id"], status="publish", category_ids=p.get("category_ids") or None, pre_approved=True)


def set_status(scheduler_id: str, active: bool) -> dict:
    tid = get_context().tenant_id
    if not fetch_one("""UPDATE public.tenant_schedulers SET status = %s WHERE id = %s AND tenant_id = %s AND category = 'articles'
                        AND coalesce((params->>'autopilot')::boolean, false) RETURNING 1""", ["active" if active else "paused", scheduler_id, tid]):
        raise BusinessError("programme not found", "not_found", status_code=404)
    record_activity("content.autopilot_resumed" if active else "content.autopilot_paused", "content", entity_type="tenant_schedulers",
                    entity_id=scheduler_id, description="Publication automatique " + ("reprise" if active else "mise en pause"))
    return {"status": "active" if active else "paused"}
