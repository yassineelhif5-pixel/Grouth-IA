"""Intelligent onboarding: analyse the product website and classify every piece of information as
detected (with evidence), confirmed (by a user), hypothesis (AI / inference) or missing. Nothing is invented."""
from __future__ import annotations

import json
import re

from django.conf import settings
from django.db import transaction

from apps.audit.services import record_activity, record_audit
from apps.core.context import get_context
from apps.core.db import fetch_one
from apps.core.exceptions import BusinessError
from apps.seo.crawler import Crawler

REQUIRED = ["name", "description", "url", "languages", "value_proposition", "positioning", "features", "pricing", "personas",
            "audiences", "icp", "competitors", "goals", "markets", "industries", "target_countries", "sales_channels"]
PRICE_RE = re.compile(r"(?:€|\$|£)\s?\d{1,5}(?:[.,]\d{2})?|\d{1,5}(?:[.,]\d{2})?\s?(?:€|\$|£|EUR|USD)(?:\s?/\s?(?:mois|month|an|year|user|utilisateur))?", re.I)


def _fact(field, value, status, source, evidence=None):
    return {"field": field, "value": value, "status": status, "source": source, "evidence": evidence}


def analyse_site(url: str) -> list[dict]:
    res = Crawler(settings.CRAWLER_USER_AGENT, max_pages=8, delay=settings.CRAWLER_DELAY_SECONDS).crawl(url)
    facts: list[dict] = []
    ok = [p for p in res.pages if p.status_code and p.status_code < 400 and p.title]
    if not ok:
        return [_fact("url", url, "missing", "crawler", "site not reachable or no HTML page")]
    home = ok[0]
    facts.append(_fact("url", home.url, "detected", home.url))
    name = home.og_tags.get("og:site_name") or (home.title.split("|")[0].split(" - ")[0].strip() if home.title else None)
    if name:
        facts.append(_fact("name", name, "detected", home.url, "og:site_name / <title>"))
    if home.meta_description:
        facts.append(_fact("description", home.meta_description, "detected", home.url, "meta description"))
    langs = sorted({p.lang.split("-")[0] for p in ok if p.lang})
    if langs:
        facts.append(_fact("languages", langs, "detected", home.url, "<html lang>"))
    if home.h1:
        facts.append(_fact("value_proposition", home.h1[0], "hypothesis", home.url, "H1 of the home page (to confirm)"))
    pricing_pages = [p for p in ok if re.search(r"pric|tarif|plan", p.url, re.I)]
    if pricing_pages:
        facts.append(_fact("pricing", {"page": pricing_pages[0].url}, "detected", pricing_pages[0].url, "pricing page found"))
    feature_pages = [p for p in ok if re.search(r"feature|fonctionnalit|product|produit", p.url, re.I)] or [home]
    feats = [t for n, t in feature_pages[0].headings if n in ("h2", "h3")][:15]
    if feats:
        facts.append(_fact("features", feats, "hypothesis", feature_pages[0].url, "section headings (to confirm)"))
    schema = sorted({t for p in ok for t in p.schema_types})
    if schema:
        facts.append(_fact("structured_data", schema, "detected", home.url, "Schema.org types"))
    found = {f["field"] for f in facts}
    facts += [_fact(f, None, "missing", None) for f in REQUIRED if f not in found]
    return facts


def run_onboarding(product_id: str) -> dict:
    tid = get_context().tenant_id
    p = fetch_one("SELECT url, primary_domain FROM public.products WHERE id = %s AND tenant_id = %s", [product_id, tid])
    if not p or not (p[0] or p[1]):
        raise BusinessError("Product URL or domain required", "url_required")
    url = p[0] or f"https://{p[1]}"
    facts = analyse_site(url)
    with transaction.atomic():
        ctx_row = fetch_one("SELECT id, facts FROM public.product_business_context WHERE product_id = %s AND tenant_id = %s AND deleted_at IS NULL",
                            [product_id, tid])
        confirmed = {f["field"]: f for f in (ctx_row[1] if ctx_row else []) if f.get("status") == "confirmed"}
        merged = [confirmed.get(f["field"], f) for f in facts] + [f for k, f in confirmed.items() if k not in {x["field"] for x in facts}]
        if ctx_row:
            fetch_one("UPDATE public.product_business_context SET facts = %s::jsonb, last_analysis_at = now() WHERE id = %s RETURNING 1",
                      [json.dumps(merged), ctx_row[0]])
            cid = ctx_row[0]
        else:
            cid = fetch_one("""INSERT INTO public.product_business_context (tenant_id, product_id, facts, last_analysis_at)
                               VALUES (%s,%s,%s::jsonb, now()) RETURNING id""", [tid, product_id, json.dumps(merged)])[0]
        fetch_one("""INSERT INTO public.product_business_context_sources (tenant_id, context_id, source_type, source_ref, extracted_at)
                     VALUES (%s,%s,'website',%s, now()) RETURNING id""", [tid, cid, url])
    counts = {s: sum(1 for f in merged if f["status"] == s) for s in ("detected", "confirmed", "hypothesis", "missing")}
    record_audit("product.onboarding_analysed", "products", entity_type="products", entity_id=product_id, after=counts)
    record_activity("product.onboarding_analysed", "products", entity_type="products", entity_id=product_id, product_id=product_id,
                    description=f"Analyse du site {url}", metadata=counts)
    return counts


FIELD_TO_COLUMN = {"name": "name", "description": "description", "url": "url", "languages": "languages", "features": "features",
                   "pricing": "pricing", "icp": "icp", "markets": "markets", "industries": "industries",
                   "target_countries": "target_countries", "sales_channels": "sales_channels"}


def confirm_fact(product_id: str, field: str, value) -> list[dict]:
    """A user confirms (or corrects) a fact → status confirmed; mapped product columns are updated (versioned)."""
    tid = get_context().tenant_id
    with transaction.atomic():
        row = fetch_one("SELECT id, facts FROM public.product_business_context WHERE product_id = %s AND tenant_id = %s AND deleted_at IS NULL FOR UPDATE",
                        [product_id, tid])
        if not row:
            raise BusinessError("Run the onboarding analysis first", "not_found", status_code=404)
        facts = [f for f in row[1] if f["field"] != field] + [_fact(field, value, "confirmed", f"user:{get_context().user_id}")]
        fetch_one("UPDATE public.product_business_context SET facts = %s::jsonb WHERE id = %s RETURNING 1", [json.dumps(facts), row[0]])
        if field in ("value_proposition", "positioning"):
            fetch_one(f"UPDATE public.product_business_context SET {field} = %s WHERE id = %s RETURNING 1", [str(value), row[0]])  # noqa: S608
        elif field in FIELD_TO_COLUMN:
            col = FIELD_TO_COLUMN[field]
            v = json.dumps(value) if col in ("features", "pricing", "icp") else value
            cast = "::jsonb" if col in ("features", "pricing", "icp") else ""
            fetch_one(f"UPDATE public.products SET {col} = %s{cast} WHERE id = %s AND tenant_id = %s RETURNING 1", [v, product_id, tid])  # noqa: S608
        record_audit("product.fact_confirmed", "products", entity_type="products", entity_id=product_id, after={"field": field})
    return facts
