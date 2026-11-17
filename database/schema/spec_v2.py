"""PROMPT 2 — additive evolution of the schema (never destructive).

New columns are emitted as ADD COLUMN IF NOT EXISTS, changed CHECK constraints are re-created,
new tables are created with the same conventions (tenant isolation, RLS, triggers, history).
"""
from dsl import domain, extend, recheck, relax, set_default, to_run

# ───────── Run tables: status transitions allowed, rows never deleted ─────────
for _t in ("website_scans", "seo_audits", "geo_audits", "ai_search_runs", "content_generation_jobs",
           "video_generation_jobs", "video_render_jobs", "connector_sync_runs", "scheduler_execution_runs",
           "scheduler_execution_steps", "growth_workflow_executions", "growth_workflow_execution_steps",
           "email_sync_runs", "notification_deliveries", "email_webhook_events"):
    to_run(_t)

# ───────── Connectors / secure integration gateway ─────────
recheck("connector_providers", "category", "analytics,crm,email,social,seo,cms,ads,storage,ai,messaging,payments,video,other")
recheck("connector_providers", "auth_type", "oauth2,api_key,basic,none,webhook,smtp,imap,app_password")
recheck("tenant_connector_accounts", "status",
        "pending,not_configured,configured,authorized,connected,tested,degraded,expired,failed,pending_approval,error,disconnected,revoked")
set_default("tenant_connector_accounts", "status", "'configured'")
extend("tenant_connector_accounts", """
settings json! ='{}' # non-secret provider settings (base_url, sender, site_url…)
last_test_at ts
last_test_status text
last_error text
expires_at ts
""")
extend("tenant_connector_credentials", "ciphertext text secret # Fernet-encrypted by the backend (SECRETS_ENCRYPTION_KEY)")
extend("connector_global_configurations", "client_secret_ciphertext text secret")
extend("connector_providers", """
capabilities text[]
docs_status text! ='available' in(available,pending_approval,not_implemented)
""")

# ───────── AI providers & routing ─────────
extend("ai_provider_configurations", """
api_key_ciphertext text secret
base_url text
priority int! =100
monthly_budget_cents bigint
last_test_at ts
last_test_status text
""")
extend("ai_providers", "api_style text! ='openai' in(openai,anthropic,gemini,cohere,azure_openai,ollama)")
extend("ai_execution_logs", """
provider_code text
model_code text
feature_code text
prompt_version text
user_id uuid
""")
t = domain("S. Fournisseurs IA", "ai_providers")
t("ai_feature_routes", """
tenant_id uuid -> tenants cascade # null = platform route
feature_code text! # content.generate, geo.query, email.classify, thor.chat…
model_id uuid! -> ai_models
priority int! =1
quality text! ='standard' in(economy,standard,premium)
max_latency_ms int
is_enabled bool! =true
""", kind="ref", read="pilot", unique=[("tenant_id", "feature_code", "model_id")])

# ───────── Growth modes, approvals ─────────
t = domain("C. Autorisations", "permissions")
t("platform_action_capabilities", """
module_code text!
action_code text!
max_mode text! ='approval' in(automatic,approval,analysis,disabled)
description text
""", kind="ref", unique=[("module_code", "action_code")])
t("tenant_growth_policies", """
module_code text!
action_code text!
mode text! ='approval' in(automatic,approval,analysis,disabled)
growth_mode text! ='assisted' in(assisted,autonomous,hybrid)
""", kind="conf", unique=[("tenant_id", "module_code", "action_code")])
t("approval_requests", """
module_code text!
action_code text!
entity_type text
entity_id uuid
product_id uuid -> products
payload json! ='{}'
status text! ='pending' in(pending,approved,rejected,expired,executed,failed)
requested_by uuid -> auth.users setnull
requested_by_agent text
decided_by uuid -> auth.users setnull
decided_at ts
decision_reason text
execution_id uuid
expires_at ts
""", index=[("tenant_id", "status")])

# ───────── Products & onboarding ─────────
extend("products", """
product_type text! ='saas' in(saas,website,ecommerce,marketplace,app,service,other)
url text
languages text[]
target_countries text[]
markets text[]
industries text[]
features json! ='[]'
pricing json! ='{}'
icp json! ='{}'
sales_channels text[]
""")
extend("product_business_context", """
facts json! ='[]' # [{field,value,status: detected|confirmed|hypothesis|missing,source,evidence}]
last_analysis_at ts
""")

# ───────── SEO ─────────
extend("seo_audits", """
website_id uuid -> websites
audit_type text! ='full' in(full,technical,onpage,keywords,competitors,backlinks,content_gap)
pages_limit int! =50
issues_count int! =0
summary json! ='{}'
error_message text
""")
extend("seo_audit_pages", """
status_code int
load_ms int
""")
extend("seo_issues", """
category text
page_url text
details json! ='{}'
impact text in(low,medium,high)
""")
extend("seo_recommendations", """
audit_id uuid -> seo_audits
category text
difficulty text in(low,medium,high)
estimated_impact text
details json! ='{}'
""")

# ───────── GEO ─────────
extend("ai_search_queries", """
engines text[]
competitor_names text[]
""")
extend("ai_search_runs", """
provider_code text
model_code text
method text! ='api_answer' in(api_answer,api_search,manual_import)
cost_cents num
duration_ms int
error_message text
""")
extend("ai_crawler_registry", "purpose text! ='crawl' in(crawl,search,training,user_fetch)")
extend("geo_audits", """
website_id uuid -> websites
summary json! ='{}'
error_message text
""")

# ───────── Content factory ─────────
extend("generated_contents", """
product_id uuid -> products
keyword text
campaign text
objective text
channel text
domain text
author_id uuid -> auth.users setnull
agent_code text
prompt_template_code text
prompt_version text
model_code text
provider_code text
cost_cents num
seo_score num
geo_score num
sources json! ='[]'
scheduled_at ts
published_url text
""")
extend("content_versions", """
source text! ='manual' in(ai,manual,restore,translation,optimization)
model_code text
prompt_version text
author_id uuid
""")
extend("content_publications", """
connector_account_id uuid -> tenant_connector_accounts
external_id text
error_message text
""")
recheck("generated_contents", "content_type",
        "article,guide,tutorial,comparison,faq,case_study,product_page,feature_page,landing_page,industry_page,"
        "linkedin_post,facebook_post,instagram_post,x_post,newsletter,video_script,page,email,social_post,ad,other")

# ───────── Page builder ─────────
t = domain("H. Content", "content")
t("builder_templates", """
tenant_id uuid -> tenants cascade
name text!
page_type text!
sections json! ='[]'
""", kind="gbiz", read="member_or_shared")
t("builder_pages", """
product_id uuid -> products
website_id uuid -> websites
template_id uuid -> builder_templates setnull
page_type text! in(landing,product,feature,comparison,industry,seo,conversion)
title text!
slug text!
sections json! ='[]' # [{type,props}] rendered server-side to HTML
seo json! ='{}'
status text! ='draft' in(draft,review,approved,published,archived)
connector_account_id uuid -> tenant_connector_accounts
external_id text
published_url text
""", unique=[("tenant_id", "website_id", "slug")])
t("builder_page_versions", """
page_id uuid! -> builder_pages
version int!
title text
sections json!
seo json
author_id uuid
""", kind="log", unique=[("tenant_id", "page_id", "version")])

# ───────── Social ─────────
recheck("social_accounts", "platform", "linkedin,x,facebook,instagram,tiktok,youtube,pinterest,reddit,other")
extend("social_accounts", "status text! ='configured' in(configured,connected,expired,failed,disconnected)")
extend("social_publications", """
scheduled_at ts
media json! ='[]'
attempts int! =0
error_message text
published_url text
""")
recheck("social_publications", "status", "draft,approved,scheduled,publishing,published,failed,cancelled")

# ───────── Video ─────────
extend("video_projects", "format text! ='short' in(short,long)")
extend("video_assets", """
source text! ='uploaded' in(uploaded,generated,rendered)
mime_type text
size_bytes bigint
duration_seconds num
""")
extend("video_generation_jobs", """
provider_code text
cost_cents num
output_asset_id uuid -> video_assets
""")

# ───────── Opportunity hunter ─────────
_OPP_STATUS = "new,detected,under_analysis,qualified,approved,in_progress,won,rejected,archived,lost,dismissed"
for _t in ("market_opportunities", "saas_opportunities", "website_opportunities", "keyword_opportunities",
           "customer_opportunities", "trend_opportunities", "partnership_opportunities", "revenue_opportunities"):
    recheck(_t, "status", _OPP_STATUS)
    extend(_t, """
product_id uuid -> products
source_id uuid -> opportunity_sources
hunter text
confidence num
potential num
difficulty num
recommendation text
dedup_hash text
detected_at ts! =now()
""")
extend("opportunity_search_projects", """
hunters text[]
config json! ='{}'
""")

t = domain("J. Opportunity Hunter", "opportunities")
t("social_listening_configs", """
product_id uuid -> products
name text!
keywords text[]
negative_keywords text[]
industries text[]
countries text[]
languages text[]
personas text[]
sources text[] # hackernews, reddit, rss:<url>
frequency text! ='daily' in(hourly,daily,weekly)
status text! ='active' in(active,paused)
last_run_at ts
""")
t("social_signals", """
config_id uuid! -> social_listening_configs
source text!
external_id text!
url text
author_handle text
title text
content text
published_at ts
language text
intent text in(software_request,recommendation_request,business_need,solution_search,problem,commercial_intent,discussion)
score num
confidence num
dedup_hash text!
status text! ='new' in(new,qualified,assigned,dismissed,converted)
assigned_to uuid -> auth.users setnull
evidence json! ='{}'
""", unique=[("tenant_id", "dedup_hash")])

# ───────── Smart prospect ─────────
extend("prospect_projects", "icp json! ='{}' # {industries,company_sizes,countries,functions,technologies,needs}")
recheck("prospects", "status",
        "new,new_lead,enriched,contacted,qualified,interested,demo_requested,meeting_scheduled,proposal_sent,"
        "negotiation,customer,lost,replied,converted,disqualified,unsubscribed")
extend("prospects", """
product_id uuid -> products
score num
confidence num
need_detected text
source_detail text
last_activity_at ts
""")
extend("prospect_companies", """
size_employees int
technologies text[]
source text
""")
extend("prospect_campaigns", """
channel text! ='email' in(email,whatsapp)
product_id uuid -> products
settings json! ='{}'
""")
extend("prospect_messages", """
channel text! ='email' in(email,whatsapp)
error_message text
provider_message_id text
""")

# ───────── Email center ─────────
extend("email_mailboxes", """
connector_account_id uuid -> tenant_connector_accounts
receive_mode text! ='none' in(none,webhook,gmail,graph,imap)
send_enabled bool! =true
last_sync_at ts
sync_error text
""")
extend("email_conversations", """
labels text[]
is_unread bool! =false
assigned_to uuid -> auth.users setnull
product_id uuid -> products
last_inbound_at ts
last_outbound_at ts
""")
extend("email_messages", """
status text! ='received' in(draft,queued,sent,accepted,delivered,deferred,bounced,failed,received)
is_read bool! =false
classification text
provider_thread_id text
headers json! ='{}'
sent_by uuid
error_message text
""")
extend("email_message_attachments", """
verification_status text! ='pending' in(pending,clean,rejected,infected,not_scanned)
sha256 text
""")
recheck("email_reply_classifications", "category",
        "interested,demo_requested,pricing_request,information_request,meeting_request,negotiation,not_interested,"
        "unsubscribe,out_of_office,automatic_reply,human_review_required,question,bounce,other")
extend("email_reply_classifications", """
summary text
intents json! ='[]'
questions json! ='[]'
objections json! ='[]'
next_action text
provider_code text
cost_cents num
method text! ='rules' in(rules,ai)
""")
extend("email_reply_drafts", """
conversation_id uuid -> email_conversations
sent_message_id uuid -> email_messages
generated_by text! ='thor' in(thor,user)
model_code text
""")
extend("email_webhook_events", """
signature_valid bool
status text! ='received' in(received,processed,rejected,failed,duplicate)
error_message text
""")

# ───────── WhatsApp center ─────────
t = domain("L2. WhatsApp Center", "whatsapp")
t("whatsapp_accounts", """
connector_account_id uuid -> tenant_connector_accounts
phone_number_id text!
waba_id text
display_phone text
status text! ='configured' in(configured,connected,failed,disconnected)
""", unique=[("tenant_id", "phone_number_id")])
t("whatsapp_templates", """
account_id uuid! -> whatsapp_accounts cascade
name text!
language text! ='fr'
category text
status text! ='pending' in(pending,approved,rejected,paused)
components json! ='[]'
""", kind="conf", unique=[("tenant_id", "account_id", "name", "language")])
t("whatsapp_contacts", """
wa_id text!
prospect_contact_id uuid -> prospect_contacts setnull
display_name text
consent_status text! ='unknown' in(unknown,opted_in,opted_out)
consent_source text
consent_at ts
last_inbound_at ts
""", unique=[("tenant_id", "wa_id")])
t("whatsapp_conversations", """
account_id uuid! -> whatsapp_accounts
contact_id uuid! -> whatsapp_contacts
status text! ='open' in(open,pending,closed)
assigned_to uuid -> auth.users setnull
is_unread bool! =false
last_message_at ts
""", unique=[("tenant_id", "account_id", "contact_id")])
t("whatsapp_messages", """
conversation_id uuid! -> whatsapp_conversations
direction text! in(inbound,outbound)
wa_message_id text
message_type text! ='text'
body text
template_name text
status text! ='received' in(queued,sent,delivered,read,failed,received)
error_message text
sent_by uuid
""", index=[("tenant_id", "wa_message_id")])
t("whatsapp_webhook_events", """
account_id uuid -> whatsapp_accounts
idempotency_key text! uniq
signature_valid bool
event_type text!
payload json!
""", kind="log", read="admin")

# ───────── CRM ─────────
extend("crm_opportunities", "product_id uuid -> products")
extend("crm_activities", """
channel text
actor_type text! ='user' in(user,thor,system,prospect)
entity_ref json! ='{}'
""")
recheck("crm_activities", "activity_type", "call,email,meeting,note,task,whatsapp,status_change,thor_action")

# ───────── Scheduler ─────────
extend("tenant_schedulers", """
category text! ='reporting' in(seo,geo,articles,pages,social,videos,opportunities,social_monitoring,prospects,crm,reporting,intelligence,agents)
frequency_type text! ='daily' in(hourly,every_x_hours,daily,weekly,monthly,cron,event,conditional)
frequency_value text # X hours | HH:MM | weekday HH:MM | day HH:MM | cron | event name
params json! ='{}'
agent_code text
mode text! ='approval' in(automatic,approval,analysis)
budget_cents bigint
quota_limit int
next_run_at ts
last_run_at ts
last_status text
""")
relax("scheduler_execution_runs", "task_id")
extend("scheduler_execution_runs", """
scheduler_id uuid -> tenant_schedulers
cost_cents num
result json
""")

# ───────── Workflow engine ─────────
extend("growth_workflow_executions", """
input json! ='{}'
context json! ='{}'
current_node text
cancel_requested bool! =false
""")
recheck("growth_workflow_execution_steps", "status", "pending,running,succeeded,failed,skipped,waiting_approval,cancelled,retrying")
extend("growth_workflow_execution_steps", """
attempt int! =1
idempotency_key text
next_retry_at ts
""")
recheck("growth_workflow_executions", "status", "queued,running,succeeded,failed,cancelled,waiting_approval,paused")

# ───────── Growth intelligence ─────────
extend("growth_recommendations", """
rule_code text
dedup_key text
sources json! ='[]'
justification text
confidence num
impact text
difficulty text
risks json! ='[]'
actions json! ='[]'
nature text! ='recommendation' in(fact,hypothesis,recommendation)
""")
extend("growth_intelligence_insights", """
rule_code text
sources json! ='[]'
nature text! ='fact' in(fact,hypothesis)
""")

# ───────── THOR ─────────
extend("thor_messages", """
provider_code text
cost_cents num
duration_ms int
prompt_version text
tool_calls json
""")
extend("thor_tool_executions", """
duration_ms int
approval_request_id uuid -> approval_requests
""")
