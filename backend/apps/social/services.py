"""Social publisher (official APIs only) and Video Studio. A video *script* is text; a *video* exists only
when a provider produced a file stored in Supabase Storage (video_assets with source=generated/rendered)."""
from __future__ import annotations

import json

from django.db import transaction

from apps.ai_providers.gateway import complete
from apps.audit.services import record_activity, record_audit
from apps.core.context import get_context
from apps.core.db import fetch_one
from apps.core.exceptions import BusinessError
from apps.integrations.gateway import get_credentials, http, load_account
from apps.permissions.growth import gate, register

SUPPORTED = {"linkedin", "facebook"}  # others: pending provider app review


def _post(platform: str, account_id: str, body: str, media: list) -> tuple[str, str]:
    acc = load_account(account_id)
    if platform == "linkedin":
        from apps.integrations.providers import access_token
        tok = access_token(acc.id)
        author = acc.settings.get("author_urn")
        if not author:
            raise BusinessError("LinkedIn author URN not configured", "connector_not_configured", status_code=409)
        r = http("POST", "https://api.linkedin.com/rest/posts", provider="linkedin", operation="post", account_id=acc.id,
                 headers={"Authorization": f"Bearer {tok}", "LinkedIn-Version": acc.settings.get("api_version", "202410"),
                          "X-Restli-Protocol-Version": "2.0.0"},
                 json={"author": author, "commentary": body, "visibility": "PUBLIC", "lifecycleState": "PUBLISHED",
                       "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []}})
        pid = r.headers.get("x-restli-id", "")
        return pid, f"https://www.linkedin.com/feed/update/{pid}"
    if platform == "facebook":
        page_id, token = acc.settings.get("page_id"), get_credentials(acc.id).get("page_access_token")
        if not page_id or not token:
            raise BusinessError("Facebook page id / page token missing", "connector_not_configured", status_code=409)
        d = http("POST", f"https://graph.facebook.com/v21.0/{page_id}/feed", provider="facebook", operation="post", account_id=acc.id,
                 data={"message": body, "access_token": token}).json()
        return d["id"], f"https://www.facebook.com/{d['id']}"
    raise BusinessError(f"{platform} publishing requires provider app approval (not available yet)", "pending_approval", status_code=501)


@register("social", "publish")
def publish_now(approval: dict) -> dict:
    pid = approval["entity_id"]
    tid = get_context().tenant_id
    row = fetch_one("""SELECT p.body, p.media, a.platform, a.connector_account_id FROM public.social_publications p
                         JOIN public.social_accounts a ON a.id = p.social_account_id WHERE p.id = %s AND p.tenant_id = %s""", [pid, tid])
    if not row:
        raise BusinessError("publication not found", "not_found", status_code=404)
    body, media, platform, account = row
    fetch_one("UPDATE public.social_publications SET status = 'publishing', attempts = attempts + 1 WHERE id = %s RETURNING 1", [pid])
    try:
        if not account:
            raise BusinessError("Social account not connected", "connector_not_configured", status_code=409)
        ext, url = _post(platform, str(account), body or "", media or [])
    except BusinessError as e:
        fetch_one("UPDATE public.social_publications SET status = 'failed', error_message = %s WHERE id = %s RETURNING 1", [e.message, pid])
        record_audit("social.publish_failed", "social", entity_type="social_publications", entity_id=pid, status="failure", description=e.message)
        from apps.notifications.service import notify
        notify("publication.failed", {"title": f"{platform}", "error": e.message}, permission="social.publish")
        raise
    fetch_one("""UPDATE public.social_publications SET status = 'published', external_post_id = %s, published_url = %s, published_at = now(),
                   error_message = NULL WHERE id = %s RETURNING 1""", [ext, url, pid])
    record_audit("social.published", "social", entity_type="social_publications", entity_id=pid, after={"platform": platform, "url": url})
    return {"status": "published", "url": url}


def request_publish(pub_id: str) -> dict:
    st = fetch_one("SELECT status FROM public.social_publications WHERE id = %s AND tenant_id = %s", [pub_id, get_context().tenant_id])
    if not st or st[0] not in ("draft", "approved", "scheduled", "failed"):
        raise BusinessError("Publication cannot be published in its current state", "invalid_state", status_code=409)
    decision, approval = gate("social", "publish", entity_type="social_publications", entity_id=pub_id, payload={})
    return publish_now({"entity_id": pub_id}) if decision == "execute" else {"status": decision, "approval_id": approval}


def generate_post(product_id: str | None, platform: str, topic: str) -> str:
    from apps.content.services import product_context
    r = complete("content.generate", [{"role": "user", "content": f"Platform: {platform}\nTopic: {topic}\nProduct facts: {product_context(product_id)}"}],
                 system="Write one social media post adapted to the platform's norms and length. Use only provided facts; no invented claims.",
                 max_tokens=600, product_id=product_id, agent_code="social_writer", prompt_version="social-builtin-v1")
    return r.text


# ───────────── Video studio ─────────────
def generate_script(project_id: str, brief: str) -> str:
    tid = get_context().tenant_id
    p = fetch_one("SELECT product_id, title, format FROM public.video_projects WHERE id = %s AND tenant_id = %s", [project_id, tid])
    if not p:
        raise BusinessError("project not found", "not_found", status_code=404)
    from apps.content.services import product_context
    r = complete("content.generate", [{"role": "user", "content": f"Video title: {p[1]}\nFormat: {p[2]} ({'≤60s' if p[2] == 'short' else '3-10 min'})\n"
                                                                     f"Brief: {brief}\nProduct facts: {product_context(str(p[0]))}\n"
                                                                     "Return JSON: {\"script\": str, \"scenes\": [{\"description\": str, \"duration_seconds\": number, \"voiceover\": str}]}"}],
                 system="You write video scripts and storyboards. Use only provided facts.", max_tokens=2500, product_id=str(p[0]),
                 agent_code="video_writer", prompt_version="video-builtin-v1")
    data = r.json()
    with transaction.atomic():
        sid = fetch_one("INSERT INTO public.video_scripts (tenant_id, project_id, body) VALUES (%s,%s,%s) RETURNING id", [tid, project_id, data["script"]])[0]
        sb = fetch_one("INSERT INTO public.video_storyboards (tenant_id, project_id, script_id, data) VALUES (%s,%s,%s,%s::jsonb) RETURNING id",
                       [tid, project_id, sid, json.dumps(data)])[0]
        for i, sc in enumerate(data.get("scenes", []), 1):
            fetch_one("INSERT INTO public.video_scenes (tenant_id, storyboard_id, position, description, duration_seconds) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                      [tid, sb, i, sc.get("description"), sc.get("duration_seconds")])
        fetch_one("UPDATE public.video_projects SET status = 'scripting' WHERE id = %s RETURNING 1", [project_id])
    record_activity("video.script_generated", "video", entity_type="video_projects", entity_id=project_id, product_id=str(p[0]))
    return str(sid)


def subtitles_srt(storyboard_id: str) -> str:
    """Real SRT file built from the storyboard voice-over timings."""
    data = fetch_one("SELECT data FROM public.video_storyboards WHERE id = %s AND tenant_id = %s", [storyboard_id, get_context().tenant_id])
    if not data:
        raise BusinessError("storyboard not found", "not_found", status_code=404)
    t, out = 0.0, []
    def fmt(x):
        return f"{int(x // 3600):02}:{int(x % 3600 // 60):02}:{int(x % 60):02},{int(x * 1000 % 1000):03}"
    for i, sc in enumerate(data[0].get("scenes", []), 1):
        d = float(sc.get("duration_seconds") or 3)
        out.append(f"{i}\n{fmt(t)} --> {fmt(t + d)}\n{sc.get('voiceover') or sc.get('description', '')}\n")
        t += d
    return "\n".join(out)


def request_render(project_id: str, provider: str | None) -> dict:
    """Video generation needs a configured video provider; without one the job is recorded as failed (not simulated)."""
    tid = get_context().tenant_id
    job = fetch_one("INSERT INTO public.video_generation_jobs (tenant_id, project_id, status, provider_code, execution_id) VALUES (%s,%s,'failed',%s,%s) RETURNING id",
                    [tid, project_id, provider, get_context().execution_id])[0]
    msg = "No video generation provider is configured (connect one in Connectors)"
    fetch_one("UPDATE public.video_generation_jobs SET error_message = %s WHERE id = %s RETURNING 1", [msg, job])
    record_audit("video.render_requested", "video", entity_type="video_generation_jobs", entity_id=job, status="failure", description=msg)
    return {"job_id": str(job), "status": "failed", "error": msg}
