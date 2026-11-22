"""Conversation-first marketing strategy services. No website crawling or automatic site analysis."""
from __future__ import annotations

import json

from apps.ai_providers.gateway import complete
from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError

SYSTEM = (
    "You are the Marketing Strategist inside Growth IA. Speak French unless the user uses another language. "
    "Build the tenant's marketing understanding ONLY from what the user says in this conversation and saved profile. "
    "Never crawl, inspect, audit or infer facts from the tenant website. A website URL is optional reference text only. "
    "Ask concise follow-up questions when essential context is missing. Distinguish user-provided facts from hypotheses. "
    "Never invent search volumes, keyword difficulty, market shares, competitor facts or performance metrics. "
    "Help the owner define audience, offer, differentiators, objectives, editorial themes, article ideas and keywords. "
    "A proposed strategy is not approved until the owner explicitly approves it. Never publish or schedule content from this chat."
)


def _tid():
    return get_context().tenant_id


def get_profile() -> dict:
    tid = _tid()
    row = fetch_one("""SELECT id, company_name, industry, offer, target_audience, differentiators, objectives,
                             preferred_language, website_url, timezone, publishing_policy
                        FROM public.tenant_marketing_profiles WHERE tenant_id=%s AND deleted_at IS NULL""", [tid])
    if not row:
        return {}
    keys = ("id", "company_name", "industry", "offer", "target_audience", "differentiators", "objectives",
            "preferred_language", "website_url", "timezone", "publishing_policy")
    return dict(zip(keys, row, strict=True))


def save_profile(data: dict) -> dict:
    tid, uid = _tid(), get_context().user_id
    allowed = {"company_name", "industry", "offer", "target_audience", "differentiators", "objectives",
               "preferred_language", "website_url", "timezone"}
    values = {k: data[k] for k in allowed if k in data}
    if "website_url" in values:
        # URL is stored as an optional content reference; no fetch/crawl is performed.
        values["website_url"] = (values["website_url"] or "").strip() or None
    if "objectives" in values:
        if not isinstance(values["objectives"], list):
            raise BusinessError("objectives must be a list", "invalid")
        values["objectives"] = json.dumps(values["objectives"], ensure_ascii=False)
    if not values:
        return get_profile()
    existing = fetch_one("SELECT id FROM public.tenant_marketing_profiles WHERE tenant_id=%s AND deleted_at IS NULL", [tid])
    if existing:
        sets = ", ".join(f"{k}={'%s::jsonb' if k == 'objectives' else '%s'}" for k in values)
        fetch_one(f"UPDATE public.tenant_marketing_profiles SET {sets}, updated_by=%s WHERE tenant_id=%s AND deleted_at IS NULL RETURNING id",
                  [*values.values(), uid, tid])
    else:
        cols = ["tenant_id", *values.keys(), "created_by", "updated_by"]
        marks = ["%s::jsonb" if k == "objectives" else "%s" for k in values]
        marks = ["%s", *marks, "%s", "%s"]
        args = [tid, *values.values(), uid, uid]
        fetch_one(f"INSERT INTO public.tenant_marketing_profiles ({', '.join(cols)}) VALUES ({', '.join(marks)}) RETURNING id", args)
    return get_profile()


def list_conversations() -> list[dict]:
    return fetch_all_dict("""SELECT id, title, status, created_at, updated_at FROM public.tenant_marketing_conversations
                              WHERE tenant_id=%s AND user_id=%s AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 50""",
                          [_tid(), get_context().user_id])


def get_messages(conversation_id: str) -> list[dict]:
    owned = fetch_one("""SELECT id FROM public.tenant_marketing_conversations
                          WHERE id=%s AND tenant_id=%s AND user_id=%s AND deleted_at IS NULL""",
                      [conversation_id, _tid(), get_context().user_id])
    if not owned:
        raise BusinessError("Conversation introuvable.", "not_found", status_code=404)
    return fetch_all_dict("""SELECT id, role, content, metadata, provider_code, model_code, created_at
                              FROM public.tenant_marketing_messages
                             WHERE tenant_id=%s AND conversation_id=%s ORDER BY created_at, id""", [_tid(), conversation_id])


def chat(conversation_id: str | None, message: str) -> dict:
    tid, uid = _tid(), get_context().user_id
    message = (message or "").strip()
    if not message or len(message) > 12000:
        raise BusinessError("Le message est obligatoire (12 000 caractères maximum).", "invalid")
    if conversation_id:
        exists = fetch_one("SELECT id FROM public.tenant_marketing_conversations WHERE id=%s AND tenant_id=%s AND user_id=%s AND deleted_at IS NULL",
                           [conversation_id, tid, uid])
        if not exists:
            raise BusinessError("Conversation introuvable.", "not_found", status_code=404)
    else:
        conversation_id = str(fetch_one("""INSERT INTO public.tenant_marketing_conversations (tenant_id,user_id,title)
                                           VALUES (%s,%s,%s) RETURNING id""", [tid, uid, message[:120]])[0])
    fetch_one("INSERT INTO public.tenant_marketing_messages (tenant_id,conversation_id,role,content) VALUES (%s,%s,'user',%s) RETURNING id",
              [tid, conversation_id, message])
    profile = get_profile()
    history = fetch_all_dict("""SELECT role, content FROM public.tenant_marketing_messages
                                  WHERE tenant_id=%s AND conversation_id=%s ORDER BY created_at DESC LIMIT 16""", [tid, conversation_id])[::-1]
    context = {k: profile.get(k) for k in ("company_name", "industry", "offer", "target_audience", "differentiators", "objectives", "preferred_language")}
    user_messages = [{"role": x["role"], "content": x["content"]} for x in history]
    prompt = "Tenant marketing profile (user supplied, may be incomplete):\\n" + json.dumps(context, ensure_ascii=False, default=str) + "\\n\\nConversation:"
    result = complete("thor.chat", user_messages, system=SYSTEM + "\\n" + prompt, max_tokens=1300, agent_code="marketing_strategist",
                      prompt_version="tenant-marketing-conversation-v1", untrusted=True)
    answer = result.text or "Pour affiner votre stratégie, pouvez-vous préciser votre objectif marketing prioritaire ?"
    fetch_one("""INSERT INTO public.tenant_marketing_messages
                 (tenant_id,conversation_id,role,content,provider_code,model_code,input_tokens,output_tokens,cost_cents)
                 VALUES (%s,%s,'assistant',%s,%s,%s,%s,%s,%s) RETURNING id""",
              [tid, conversation_id, answer, result.provider, result.model, result.input_tokens, result.output_tokens, result.cost_cents])
    fetch_one("UPDATE public.tenant_marketing_conversations SET updated_at=now() WHERE id=%s AND tenant_id=%s RETURNING id", [conversation_id, tid])
    return {"conversation_id": conversation_id, "answer": answer, "provider": result.provider, "model": result.model,
            "profile": get_profile()}


def propose_strategy(conversation_id: str) -> dict:
    tid, uid = _tid(), get_context().user_id
    conv = fetch_one("SELECT id FROM public.tenant_marketing_conversations WHERE id=%s AND tenant_id=%s AND user_id=%s AND deleted_at IS NULL",
                     [conversation_id, tid, uid])
    if not conv:
        raise BusinessError("Conversation introuvable.", "not_found", status_code=404)
    messages = get_messages(conversation_id)
    if not any(m["role"] == "user" for m in messages):
        raise BusinessError("Échangez d'abord avec l'assistant pour définir vos besoins.", "invalid")
    schema_prompt = (
      "À partir uniquement des informations de la conversation, produis une stratégie marketing JSON valide, sans Markdown. "
      "Format obligatoire: {title, summary, objectives:[], target_audiences:[], positioning, editorial_pillars:[], "
      "articles:[{title, angle, primary_keyword, secondary_keywords:[], search_intent, faq:[]}], "
      "channels:[], recommended_frequency, campaign_duration_weeks, assumptions:[], questions:[]}. "
      "Propose 4 à 8 idées d'articles réalistes. N'invente aucune métrique SEO. Si les informations manquent, mets-les dans questions/assumptions. "
      "Ne lance aucun crawl, aucune publication et aucun scheduler."
    )
    transcript = "\\n".join(f"{m['role']}: {m['content']}" for m in messages[-24:])
    r = complete("thor.chat", [{"role":"user","content":schema_prompt + "\\n\\n" + transcript}],
                 system=SYSTEM, max_tokens=2600, agent_code="marketing_strategist",
                 prompt_version="tenant-marketing-strategy-v1", untrusted=True)
    try:
        data = r.json()
        if not isinstance(data, dict) or not isinstance(data.get("articles"), list):
            raise ValueError("Invalid strategy shape")
    except (ValueError, TypeError, json.JSONDecodeError) as err:
        raise BusinessError("La proposition IA n'a pas retourné un format exploitable. Réessayez.", "invalid_ai_output", status_code=502) from err
    title = str(data.get("title") or "Stratégie marketing proposée")[:240]
    summary = str(data.get("summary") or "")[:10000]
    sid = fetch_one("""INSERT INTO public.tenant_marketing_strategies
                       (tenant_id,conversation_id,title,summary,strategy,status,created_by,updated_by)
                       VALUES (%s,%s,%s,%s,%s::jsonb,'proposed',%s,%s) RETURNING id""",
                    [tid, conversation_id, title, summary, json.dumps(data, ensure_ascii=False), uid, uid])[0]
    return {"id": str(sid), "title": title, "summary": summary, "strategy": data, "status": "proposed",
            "provider": r.provider, "model": r.model}


def list_strategies() -> list[dict]:
    return fetch_all_dict("""SELECT id,conversation_id,title,summary,strategy,status,approved_at,created_at,updated_at
                              FROM public.tenant_marketing_strategies WHERE tenant_id=%s AND deleted_at IS NULL
                             ORDER BY created_at DESC LIMIT 50""", [_tid()])


def update_strategy(strategy_id: str, data: dict) -> dict:
    row = fetch_one("SELECT strategy,status FROM public.tenant_marketing_strategies WHERE id=%s AND tenant_id=%s AND deleted_at IS NULL",
                    [strategy_id, _tid()])
    if not row:
        raise BusinessError("Stratégie introuvable.", "not_found", status_code=404)
    if row[1] not in ("draft", "proposed"):
        raise BusinessError("Une stratégie déjà approuvée ne peut plus être modifiée.", "invalid_state", status_code=409)
    strategy = data.get("strategy")
    if not isinstance(strategy, dict) or not isinstance(strategy.get("articles"), list):
        raise BusinessError("Le contenu de la stratégie est invalide.", "invalid")
    title = str(data.get("title") or "Stratégie marketing proposée")[:240]
    summary = str(data.get("summary") or "")[:10000]
    fetch_one("""UPDATE public.tenant_marketing_strategies SET title=%s,summary=%s,strategy=%s::jsonb,updated_by=%s
                  WHERE id=%s AND tenant_id=%s RETURNING id""",
              [title, summary, json.dumps(strategy, ensure_ascii=False), get_context().user_id, strategy_id, _tid()])
    return {"id": strategy_id, "title": title, "summary": summary, "strategy": strategy, "status": row[1]}


def approve_strategy(strategy_id: str) -> dict:
    tid, uid = _tid(), get_context().user_id
    row = fetch_one("SELECT status FROM public.tenant_marketing_strategies WHERE id=%s AND tenant_id=%s AND deleted_at IS NULL", [strategy_id, tid])
    if not row:
        raise BusinessError("Stratégie introuvable.", "not_found", status_code=404)
    if row[0] != "proposed":
        raise BusinessError("Seule une proposition en attente peut être approuvée.", "invalid_state", status_code=409)
    fetch_one("""UPDATE public.tenant_marketing_strategies SET status='approved',approved_by=%s,approved_at=now(),updated_by=%s
                  WHERE id=%s AND tenant_id=%s RETURNING id""", [uid, uid, strategy_id, tid])
    return {"id": strategy_id, "status": "approved", "approved_at": fetch_one("SELECT approved_at FROM public.tenant_marketing_strategies WHERE id=%s", [strategy_id])[0]}


def list_campaigns() -> list[dict]:
    return fetch_all_dict("""SELECT c.id,c.strategy_id,c.name,c.status,c.timezone,c.generation_time,c.publish_requires_approval,
                                    c.starts_on,c.ends_on,c.created_at,
                                    (SELECT count(*) FROM public.tenant_marketing_editorial_items i
                                      WHERE i.tenant_id=c.tenant_id AND i.campaign_id=c.id AND i.deleted_at IS NULL) AS article_count,
                                    coalesce((SELECT json_agg(json_build_object(
                                      'id',i.id,'title',i.title,'angle',i.angle,'primary_keyword',i.primary_keyword,
                                      'secondary_keywords',i.secondary_keywords,'search_intent',i.search_intent,
                                      'status',i.status,'planned_for',i.planned_for,'published_url',i.published_url
                                    ) ORDER BY i.planned_for,i.created_at)
                                      FROM public.tenant_marketing_editorial_items i
                                     WHERE i.tenant_id=c.tenant_id AND i.campaign_id=c.id AND i.deleted_at IS NULL),'[]'::json) AS articles
                               FROM public.tenant_marketing_campaigns c
                              WHERE c.tenant_id=%s AND c.deleted_at IS NULL ORDER BY c.created_at DESC LIMIT 50""", [_tid()])

def create_campaign(strategy_id: str, starts_on: str | None = None) -> dict:
    import hashlib
    import re
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo

    tid, uid = _tid(), get_context().user_id
    row = fetch_one("""SELECT title,strategy,status FROM public.tenant_marketing_strategies
                        WHERE id=%s AND tenant_id=%s AND deleted_at IS NULL""", [strategy_id, tid])
    if not row:
        raise BusinessError("Stratégie introuvable.", "not_found", status_code=404)
    if row[2] != "approved":
        raise BusinessError("La stratégie doit être approuvée avant de créer un calendrier.", "approval_required", status_code=409)
    strategy = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
    articles = strategy.get("articles") or []
    if not articles:
        raise BusinessError("La stratégie ne contient aucun article.", "invalid")
    profile = get_profile()
    zone = profile.get("timezone") or "Europe/Paris"
    try:
        tz = ZoneInfo(zone)
        start = date.fromisoformat(starts_on) if starts_on else datetime.now(tz).date()
    except (ValueError, KeyError) as err:
        raise BusinessError("Date de début ou fuseau horaire invalide.", "invalid") from err
    duration = strategy.get("campaign_duration_weeks")
    try:
        weeks = max(1, min(52, int(duration or 8)))
    except (TypeError, ValueError):
        weeks = 8
    name = str(strategy.get("title") or row[0] or "Campagne marketing")[:240]
    campaign_id = fetch_one("""INSERT INTO public.tenant_marketing_campaigns
                                (tenant_id,strategy_id,name,status,timezone,generation_time,publish_requires_approval,starts_on,ends_on,created_by,updated_by)
                                VALUES (%s,%s,%s,'planned',%s,'00:00',true,%s,%s,%s,%s) RETURNING id""",
                            [tid, strategy_id, name, zone, start, start + timedelta(weeks=weeks), uid, uid])[0]
    inserted, duplicates = 0, 0
    count = len(articles)
    for index, article in enumerate(articles):
        title = str(article.get("title") or "").strip()
        keyword = str(article.get("primary_keyword") or "").strip()
        if not title or not keyword:
            duplicates += 1
            continue
        canonical = re.sub(r"\s+", " ", (title + "|" + keyword).casefold()).strip()
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        planned = start + timedelta(days=max(0, int(index * (weeks * 7) / max(count, 1))))
        result = fetch_one("""INSERT INTO public.tenant_marketing_editorial_items
                               (tenant_id,campaign_id,title,angle,primary_keyword,secondary_keywords,search_intent,faq,dedupe_hash,status,planned_for,created_by,updated_by)
                               VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,'planned',%s,%s,%s)
                               ON CONFLICT (tenant_id,dedupe_hash) WHERE deleted_at IS NULL DO NOTHING RETURNING id""",
                           [tid, campaign_id, title, article.get("angle"), keyword,
                            json.dumps(article.get("secondary_keywords") or [], ensure_ascii=False),
                            article.get("search_intent"), json.dumps(article.get("faq") or [], ensure_ascii=False),
                            digest, planned, uid, uid])
        if result:
            inserted += 1
        else:
            duplicates += 1
    return {"id": str(campaign_id), "name": name, "status": "planned", "timezone": zone,
            "generation_time": "00:00", "publish_requires_approval": True,
            "articles_created": inserted, "duplicates_skipped": duplicates,
            "note": "Calendrier préparé. Aucune génération automatique ni publication n'est activée à ce stade."}



def list_content_projects() -> list[dict]:
    return fetch_all_dict("""SELECT id,name,product_id,status
                               FROM public.content_projects
                              WHERE tenant_id=%s AND deleted_at IS NULL AND status='active'
                              ORDER BY name""", [_tid()])


def activate_campaign(campaign_id: str, content_project_id: str) -> dict:
    tid, uid = _tid(), get_context().user_id
    project = fetch_one("""SELECT id,name,product_id FROM public.content_projects
                            WHERE id=%s AND tenant_id=%s AND deleted_at IS NULL AND status='active'""",
                        [content_project_id, tid])
    if not project:
        raise BusinessError("Projet Content Studio introuvable ou inactif pour ce tenant.", "not_found", status_code=404)
    campaign = fetch_one("""SELECT id,status,generation_enabled FROM public.tenant_marketing_campaigns
                             WHERE id=%s AND tenant_id=%s AND deleted_at IS NULL""", [campaign_id, tid])
    if not campaign:
        raise BusinessError("Campagne introuvable.", "not_found", status_code=404)
    if campaign[1] not in ("planned", "paused"):
        raise BusinessError("Seule une campagne planifiée ou en pause peut être activée.", "invalid_state", status_code=409)
    if campaign[2]:
        raise BusinessError("La génération de cette campagne est déjà activée.", "already_active", status_code=409)
    fetch_one("""UPDATE public.tenant_marketing_campaigns
                    SET content_project_id=%s,generation_enabled=true,status='active',updated_by=%s
                  WHERE id=%s AND tenant_id=%s RETURNING id""", [content_project_id, uid, campaign_id, tid])
    return {"id": str(campaign_id), "status": "active", "generation_enabled": True,
            "content_project_id": str(project[0]), "content_project_name": project[1],
            "timezone": fetch_one("SELECT timezone FROM public.tenant_marketing_campaigns WHERE id=%s", [campaign_id])[0],
            "generation_time": "00:00", "publish_requires_approval": True,
            "note": "Génération automatique de brouillons activée. Aucun contenu ne sera publié sans validation et action de publication distincte."}


def pause_campaign(campaign_id: str) -> dict:
    tid, uid = _tid(), get_context().user_id
    row = fetch_one("""UPDATE public.tenant_marketing_campaigns
                          SET status='paused',generation_enabled=false,updated_by=%s
                        WHERE id=%s AND tenant_id=%s AND deleted_at IS NULL AND status='active'
                        RETURNING id""", [uid, campaign_id, tid])
    if not row:
        raise BusinessError("Campagne active introuvable.", "not_found", status_code=404)
    return {"id": str(campaign_id), "status": "paused", "generation_enabled": False}


def generate_editorial_item(item_id: str) -> dict:
    tid = _tid()
    item = fetch_one("""SELECT i.id,i.title,i.angle,i.primary_keyword,i.secondary_keywords,i.search_intent,i.faq,
                               i.generated_content_id,c.content_project_id,c.name,c.timezone
                          FROM public.tenant_marketing_editorial_items i
                          JOIN public.tenant_marketing_campaigns c ON c.id=i.campaign_id AND c.tenant_id=i.tenant_id
                         WHERE i.id=%s AND i.tenant_id=%s AND i.deleted_at IS NULL
                           AND c.status='active' AND c.generation_enabled=true""", [item_id, tid])
    if not item:
        raise BusinessError("Article éditorial non disponible pour la génération.", "not_found", status_code=404)
    project_id = item[8]
    if not project_id:
        raise BusinessError("Aucun projet Content Studio n'est associé à la campagne.", "invalid_state", status_code=409)
    project = fetch_one("""SELECT product_id FROM public.content_projects
                            WHERE id=%s AND tenant_id=%s AND deleted_at IS NULL AND status='active'""", [project_id, tid])
    if not project:
        raise BusinessError("Le projet Content Studio associé n'est plus actif.", "invalid_state", status_code=409)
    content_id = item[7]
    if not content_id:
        content_id = fetch_one("""INSERT INTO public.generated_contents
            (tenant_id,project_id,title,content_type,language,status,product_id,keyword,objective,channel,agent_code)
            VALUES (%s,%s,%s,'article',coalesce((SELECT preferred_language FROM public.tenant_marketing_profiles
             WHERE tenant_id=%s AND deleted_at IS NULL),'fr'),'draft',%s,%s,%s,'website','marketing_center')
            RETURNING id""",
            [tid, project_id, item[1], tid, project[0], item[3], item[2] or item[5] or "Article de blog informatif"])[0]
        fetch_one("""UPDATE public.tenant_marketing_editorial_items
                        SET generated_content_id=%s,updated_by=%s
                      WHERE id=%s AND tenant_id=%s RETURNING id""",
                  [content_id, get_context().user_id, item_id, tid])
    secondary = item[4] if isinstance(item[4], list) else json.loads(item[4] or "[]")
    faq = item[6] if isinstance(item[6], list) else json.loads(item[6] or "[]")
    profile = get_profile()
    brief = (
        "Rédige un article de blog original, utile et structuré en Markdown.\n"
        f"Contexte entreprise communiqué par le client : {profile.get('company_name') or '-'}; secteur : {profile.get('industry') or '-'}; "
        f"offre : {profile.get('offer') or '-'}; public : {profile.get('target_audience') or '-'}; différenciation : {profile.get('differentiators') or '-'}\n"
        f"Angle éditorial : {item[2] or '-'}\nIntention de recherche : {item[5] or '-'}\n"
        f"Mot-clé principal : {item[3]}\nMots-clés secondaires : {', '.join(secondary)}\n"
        f"Questions FAQ proposées : {json.dumps(faq, ensure_ascii=False)}\n"
        "N'invente aucune donnée chiffrée, référence, étude, client, fonctionnalité ou promesse. "
        "Si une information factuelle manque, indique clairement [À VÉRIFIER]. "
        "Structure avec une introduction, des titres H2/H3, des exemples pratiques et une conclusion. "
        "Ajoute une FAQ uniquement si les questions fournies sont pertinentes. "
        "Ne prétends pas que l'article est publié ou indexé."
    )
    from apps.content.services import generate
    result = generate(str(content_id), "generate", brief)
    fetch_one("""UPDATE public.tenant_marketing_editorial_items
                    SET status='draft',generated_at=now(),generation_error=NULL,updated_by=%s
                  WHERE id=%s AND tenant_id=%s RETURNING id""", [get_context().user_id, item_id, tid])
    return {"item_id": str(item_id), "content_id": str(content_id), "status": "draft",
            "title": item[1], "primary_keyword": item[3], **result}
