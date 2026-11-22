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
    return dict(zip(keys, row))


def save_profile(data: dict) -> dict:
    tid, uid = _tid(), get_context().user_id
    allowed = {"company_name", "industry", "offer", "target_audience", "differentiators", "objectives",
               "preferred_language", "website_url", "timezone"}
    values = {k: data[k] for k in allowed if k in data}
    if "website_url" in values:
        # URL is stored as an optional content reference; no fetch/crawl is performed.
        values["website_url"] = (values["website_url"] or "").strip() or None
    if not values:
        return get_profile()
    existing = fetch_one("SELECT id FROM public.tenant_marketing_profiles WHERE tenant_id=%s AND deleted_at IS NULL", [tid])
    if existing:
        sets = ", ".join(f"{k}=%s" for k in values)
        fetch_one(f"UPDATE public.tenant_marketing_profiles SET {sets}, updated_by=%s WHERE tenant_id=%s AND deleted_at IS NULL RETURNING id",
                  [*values.values(), uid, tid])
    else:
        cols = ["tenant_id", *values.keys(), "created_by", "updated_by"]
        marks = ["%s"] * len(cols)
        args = [tid, *values.values(), uid, uid]
        fetch_one(f"INSERT INTO public.tenant_marketing_profiles ({', '.join(cols)}) VALUES ({', '.join(marks)}) RETURNING id", args)
    return get_profile()


def list_conversations() -> list[dict]:
    return fetch_all_dict("""SELECT id, title, status, created_at, updated_at FROM public.tenant_marketing_conversations
                              WHERE tenant_id=%s AND user_id=%s AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 50""",
                          [_tid(), get_context().user_id])


def get_messages(conversation_id: str) -> list[dict]:
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
    except (ValueError, TypeError, json.JSONDecodeError):
        raise BusinessError("La proposition IA n'a pas retourné un format exploitable. Réessayez.", "invalid_ai_output", status_code=502)
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
