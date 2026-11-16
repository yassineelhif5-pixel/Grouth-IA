"""Business module domains F–L, N, O (tables ready for future Growth IA modules)."""
from dsl import domain

# ───────────────────────── F. SEO ─────────────────────────
t = domain("F. SEO", "seo")
t("seo_projects", """
product_id uuid! -> products
website_id uuid -> websites
name text!
target_country text
target_language text
status text! =\'active\' in(active,paused,archived)
""")
t("seo_audits", """
project_id uuid! -> seo_projects
execution_id uuid
status text! =\'queued\' in(queued,running,succeeded,failed,cancelled)
score num
pages_analyzed int! =0
started_at ts
completed_at ts
requested_by uuid -> auth.users setnull
""", kind="log")
t("seo_audit_pages", """
audit_id uuid! -> seo_audits cascade
page_id uuid -> website_pages
url text!
score num
data json! =\'{}\'
""", kind="log")
t("seo_issues", """
audit_id uuid! -> seo_audits
audit_page_id uuid -> seo_audit_pages
issue_code text!
severity text! in(info,low,medium,high,critical)
description text
status text! =\'open\' in(open,ignored,fixed)
""")
t("seo_recommendations", """
project_id uuid! -> seo_projects
issue_id uuid -> seo_issues setnull
title text!
description text
priority int! =3
impact text in(low,medium,high)
status text! =\'open\' in(open,in_progress,done,dismissed)
""")
t("keyword_groups", """
project_id uuid! -> seo_projects cascade
name text!
intent text in(informational,navigational,commercial,transactional)
""")
t("seo_keywords", """
project_id uuid! -> seo_projects cascade
group_id uuid -> keyword_groups setnull
keyword text!
search_volume int
difficulty num
cpc_cents num
is_tracked bool! =true
""", unique=[("tenant_id", "project_id", "keyword")])
t("keyword_rankings", """
keyword_id uuid! -> seo_keywords
position int
url text
search_engine text! =\'google\'
device text! =\'desktop\' in(desktop,mobile)
checked_on date!
""", kind="log", index=[("keyword_id", "checked_on")])
t("backlinks", """
project_id uuid! -> seo_projects
source_url text!
target_url text!
anchor_text text
domain_rating num
is_dofollow bool
first_seen_at ts
lost_at ts
""")
t("page_metrics", """
page_id uuid! -> website_pages
date date!
clicks int
impressions int
ctr num
avg_position num
sessions int
""", kind="log", index=[("page_id", "date")])
t("seo_competitor_snapshots", """
project_id uuid! -> seo_projects
competitor_id uuid -> product_competitors
data json!
""", kind="log")

# ───────────────────────── G. GEO ─────────────────────────
t = domain("G. GEO", "geo")
t("geo_audits", """
product_id uuid! -> products
execution_id uuid
status text! =\'queued\' in(queued,running,succeeded,failed,cancelled)
score num
started_at ts
completed_at ts
""", kind="log")
t("geo_audit_pages", """
audit_id uuid! -> geo_audits cascade
page_id uuid -> website_pages
url text!
score num
data json! =\'{}\'
""", kind="log")
t("ai_crawler_registry", """
code text! uniq
name text!
user_agent_pattern text!
operator text
""", kind="ref")
t("ai_crawler_checks", """
website_id uuid! -> websites
crawler_id uuid! -> ai_crawler_registry
allowed bool
robots_rule text
""", kind="log")
t("ai_crawler_visits", """
website_id uuid! -> websites
crawler_id uuid -> ai_crawler_registry
path text!
visited_at ts!
""", kind="log")
t("ai_search_queries", """
product_id uuid! -> products
query text!
locale text
is_active bool! =true
""")
t("ai_search_runs", """
query_id uuid! -> ai_search_queries
engine text! # chatgpt, perplexity, gemini, claude, copilot…
execution_id uuid
status text! in(succeeded,failed)
""", kind="log")
t("ai_search_responses", """
run_id uuid! -> ai_search_runs cascade
response_text text
raw json
""", kind="log")
t("ai_search_mentions", """
response_id uuid! -> ai_search_responses cascade
brand_entity_id uuid -> brand_entities
mention_text text
sentiment text in(positive,neutral,negative)
position int
""", kind="log")
t("ai_search_citations", """
response_id uuid! -> ai_search_responses cascade
url text!
domain text
position int
""", kind="log")
t("ai_visibility_snapshots", """
product_id uuid! -> products
engine text
visibility_score num
share_of_voice num
data json
""", kind="log")
t("brand_entities", """
product_id uuid -> products
name text!
entity_type text! in(brand,product,person,organization,competitor)
aliases text[]
""")
t("brand_entity_sources", """
brand_entity_id uuid! -> brand_entities cascade
source_url text!
source_type text
""")
t("geo_recommendations", """
product_id uuid! -> products
audit_id uuid -> geo_audits
title text!
description text
priority int! =3
status text! =\'open\' in(open,in_progress,done,dismissed)
""")

# ───────────────────────── H. CONTENT ─────────────────────────
t = domain("H. Content", "content")
t("content_projects", """
product_id uuid! -> products
name text!
status text! =\'active\' in(active,paused,archived)
""")
t("content_categories", """
name text!
slug text! uniq
parent_id uuid -> content_categories setnull
""")
t("content_tags", """
name text! uniq
""")
t("content_templates", """
name text!
content_type text!
template text!
variables json! =\'[]\'
""")
t("generated_contents", """
project_id uuid! -> content_projects
category_id uuid -> content_categories setnull
template_id uuid -> content_templates setnull
title text!
content_type text! in(article,page,email,social_post,ad,video_script,other)
body text
language text! =\'fr\'
status text! =\'draft\' in(draft,review,approved,published,archived)
tags text[]
""")
t("content_versions", """
content_id uuid! -> generated_contents cascade
version int!
title text
body text
change_note text
""", kind="log", unique=[("tenant_id", "content_id", "version")])
t("content_approvals", """
content_id uuid! -> generated_contents
reviewer_id uuid -> auth.users setnull
decision text! in(approved,rejected,changes_requested)
comment text
""", kind="log")
t("content_media", """
content_id uuid -> generated_contents setnull
storage_path text!
mime_type text
size_bytes bigint
alt_text text
""")
t("content_generation_jobs", """
content_id uuid -> generated_contents
execution_id uuid
status text! in(queued,running,succeeded,failed,cancelled)
model_code text
error_message text
""", kind="log")
t("content_publications", """
content_id uuid! -> generated_contents
channel text! in(website,cms,social,email,other)
external_url text
published_at ts
status text! in(scheduled,published,failed,unpublished)
""")
t("publication_schedules", """
content_id uuid! -> generated_contents cascade
channel text!
scheduled_at ts!
status text! =\'scheduled\' in(scheduled,done,cancelled)
""")

# ───────────────────────── I. SOCIAL ET VIDÉOS ─────────────────────────
t = domain("I. Social et vidéos", "social")
t("social_accounts", """
product_id uuid -> products
connector_account_id uuid -> tenant_connector_accounts
platform text! in(linkedin,x,facebook,instagram,tiktok,youtube,other)
handle text!
""", unique=[("tenant_id", "platform", "handle")])
t("social_publications", """
social_account_id uuid! -> social_accounts
content_id uuid -> generated_contents
body text
external_post_id text
status text! in(draft,scheduled,published,failed)
published_at ts
""")
t("social_publication_metrics", """
publication_id uuid! -> social_publications
date date!
impressions int
engagements int
clicks int
""", kind="log")
t("video_projects", """
product_id uuid! -> products
title text!
status text! =\'draft\' in(draft,scripting,production,rendering,published,archived)
""")
t("video_scripts", """
project_id uuid! -> video_projects cascade
body text!
language text! =\'fr\'
""")
t("video_storyboards", """
project_id uuid! -> video_projects cascade
script_id uuid -> video_scripts
data json! =\'{}\'
""")
t("video_scenes", """
storyboard_id uuid! -> video_storyboards cascade
position int!
description text
duration_seconds num
""")
t("video_assets", """
project_id uuid! -> video_projects cascade
asset_type text! in(image,video,audio,font,other)
storage_path text!
""")
t("video_generation_jobs", """
project_id uuid! -> video_projects
execution_id uuid
status text! in(queued,running,succeeded,failed,cancelled)
error_message text
""", kind="log")
t("video_render_jobs", """
project_id uuid! -> video_projects
execution_id uuid
status text! in(queued,running,succeeded,failed,cancelled)
output_storage_path text
""", kind="log")
t("video_subtitles", """
project_id uuid! -> video_projects cascade
language text!
storage_path text
""")
t("video_publications", """
project_id uuid! -> video_projects
social_account_id uuid -> social_accounts
external_url text
status text! in(scheduled,published,failed)
published_at ts
""")
t("video_metrics", """
publication_id uuid! -> video_publications
date date!
views int
watch_time_seconds bigint
""", kind="log")

# ───────────────────────── J. OPPORTUNITY HUNTER ─────────────────────────
t = domain("J. Opportunity Hunter", "opportunities")
t("opportunity_search_projects", """
product_id uuid -> products
name text!
objective text
status text! =\'active\' in(active,paused,archived)
""")
t("opportunity_search_queries", """
project_id uuid! -> opportunity_search_projects cascade
query text!
filters json! =\'{}\'
""")
t("opportunity_sources", """
name text!
source_type text! in(web,marketplace,social,news,directory,api,other)
url text
""")
t("opportunity_source_snapshots", """
source_id uuid! -> opportunity_sources
content_hash text
data json
storage_path text
""", kind="log")
_opp = """
project_id uuid -> opportunity_search_projects
title text!
description text
score num
status text! =\'new\' in(new,qualified,in_progress,won,lost,dismissed)
data json! =\'{}\'
"""
for name in ("market_opportunities", "saas_opportunities", "website_opportunities",
             "keyword_opportunities", "customer_opportunities", "trend_opportunities",
             "partnership_opportunities", "revenue_opportunities"):
    t(name, _opp)
_ref = "opportunity_type text! in(market,saas,website,keyword,customer,trend,partnership,revenue)\nopportunity_id uuid!\n"
t("opportunity_evidence", _ref + "source_id uuid -> opportunity_sources\nurl text\nexcerpt text", kind="log",
  index=[("opportunity_type", "opportunity_id")])
t("opportunity_scores", _ref + "score num!\nmodel_version text", kind="log", index=[("opportunity_type", "opportunity_id")])
t("opportunity_score_factors", "score_id uuid! -> opportunity_scores cascade\nfactor text!\nweight num\nvalue num", kind="log")
t("opportunity_actions", _ref + "action text!\nassigned_to uuid -> auth.users setnull\nstatus text! =\'todo\' in(todo,doing,done)\ndue_date date")
t("opportunity_followups", _ref + "note text!\nfollow_up_at ts")
t("opportunity_outcomes", _ref + "outcome text! in(won,lost,abandoned)\nvalue_cents bigint\nnote text", kind="log")
t("opportunity_alerts", _ref + "message text!\nseverity text! =\'info\' in(info,warning,critical)\nread_at ts", kind="log")

# ───────────────────────── K. SMART PROSPECT ET CRM ─────────────────────────
t = domain("K. Smart Prospect et CRM", "prospects")
t("prospect_projects", """
product_id uuid -> products
name text!
status text! =\'active\' in(active,paused,archived)
""")
t("prospect_companies", """
name text!
domain text
industry text
size_range text
country_code text
data json! =\'{}\'
""", index=[("tenant_id", "domain")])
t("prospect_sources", """
name text!
source_type text! in(import,connector,scraping,manual,api)
""")
t("prospects", """
project_id uuid -> prospect_projects
company_id uuid -> prospect_companies
source_id uuid -> prospect_sources
status text! =\'new\' in(new,enriched,qualified,contacted,replied,converted,disqualified,unsubscribed)
owner_user_id uuid -> auth.users setnull
""")
t("prospect_contacts", """
prospect_id uuid! -> prospects cascade
first_name text
last_name text
email text
phone text
job_title text
linkedin_url text
consent_status text! =\'unknown\' in(unknown,legitimate_interest,consented,opted_out)
""", index=[("tenant_id", "email")])
t("prospect_enrichment_logs", """
prospect_id uuid! -> prospects
provider text!
status text! in(succeeded,failed)
fields_updated text[]
""", kind="log")
t("prospect_scores", """
prospect_id uuid! -> prospects
score num!
model_version text
factors json
""", kind="log")
t("prospect_segments", """
project_id uuid -> prospect_projects
name text!
criteria json! =\'{}\'
""")
t("prospect_templates", """
name text!
channel text! in(email,linkedin,sms)
subject text
body text!
""")
t("prospect_campaigns", """
project_id uuid -> prospect_projects
segment_id uuid -> prospect_segments
name text!
status text! =\'draft\' in(draft,scheduled,running,paused,completed,archived)
mailbox_id uuid -> email_mailboxes
""")
t("prospect_campaign_sequences", """
campaign_id uuid! -> prospect_campaigns cascade
step int!
template_id uuid -> prospect_templates
delay_hours int! =0
""", unique=[("tenant_id", "campaign_id", "step")])
t("prospect_campaign_recipients", """
campaign_id uuid! -> prospect_campaigns
contact_id uuid! -> prospect_contacts
status text! =\'pending\' in(pending,active,completed,replied,bounced,unsubscribed,stopped)
current_step int! =0
""", unique=[("tenant_id", "campaign_id", "contact_id")])
t("prospect_messages", """
recipient_id uuid! -> prospect_campaign_recipients
sequence_id uuid -> prospect_campaign_sequences
email_message_id uuid -> email_messages
status text! in(scheduled,sent,failed,cancelled)
sent_at ts
""")
t("prospect_message_events", """
message_id uuid! -> prospect_messages
event_type text! in(sent,delivered,opened,clicked,replied,bounced,unsubscribed,complained)
occurred_at ts!
""", kind="log")
t("prospect_conversations", """
contact_id uuid! -> prospect_contacts
email_conversation_id uuid -> email_conversations
status text! =\'open\' in(open,pending,closed)
""")
t("prospect_conversation_assignments", """
conversation_id uuid! -> prospect_conversations
assigned_to uuid! -> auth.users
assigned_by uuid -> auth.users setnull
unassigned_at ts
""", kind="log")
t("prospect_suppression_lists", """
email text!
reason text! in(unsubscribed,bounced,complained,manual,legal)
""", unique=[("tenant_id", "email")])
t("crm_pipeline_stages", """
name text!
position int!
probability_pct int
is_won bool! =false
is_lost bool! =false
""", kind="conf")
t("crm_opportunities", """
prospect_id uuid -> prospects
stage_id uuid! -> crm_pipeline_stages
title text!
amount_cents bigint
currency text! =\'EUR\'
expected_close_date date
owner_user_id uuid -> auth.users setnull
""")
t("crm_activities", """
opportunity_id uuid -> crm_opportunities
prospect_id uuid -> prospects
activity_type text! in(call,email,meeting,note,task)
summary text!
occurred_at ts! =now()
""", kind="log")
t("crm_meetings", """
opportunity_id uuid -> crm_opportunities
title text!
starts_at ts!
ends_at ts
location text
""")
t("crm_tasks", """
opportunity_id uuid -> crm_opportunities
title text!
assigned_to uuid -> auth.users setnull
due_at ts
status text! =\'todo\' in(todo,doing,done,cancelled)
""")
t("prospect_commercial_assignments", """
prospect_id uuid! -> prospects
user_id uuid! -> auth.users
assigned_at ts! =now()
unassigned_at ts
""", kind="log")
t("prospect_campaign_metrics", """
campaign_id uuid! -> prospect_campaigns
date date!
sent int! =0
opened int! =0
replied int! =0
bounced int! =0
""", kind="log")

# ───────────────────────── L. EMAIL CENTER ─────────────────────────
t = domain("L. Email Center", "email_center")
t("email_provider_accounts", """
connector_account_id uuid -> tenant_connector_accounts
provider text! in(gmail,outlook,smtp,sendgrid,mailgun,ses,other)
display_name text!
status text! =\'active\' in(active,error,disabled)
""")
t("email_mailboxes", """
provider_account_id uuid! -> email_provider_accounts
address text!
display_name text
daily_send_limit int
status text! =\'active\' in(active,warming,paused,disabled)
""", unique=[("tenant_id", "address")])
t("email_mailbox_permissions", """
mailbox_id uuid! -> email_mailboxes cascade
user_id uuid! -> auth.users
can_read bool! =true
can_send bool! =false
""", kind="conf", unique=[("tenant_id", "mailbox_id", "user_id")])
t("email_sync_cursors", """
mailbox_id uuid! -> email_mailboxes cascade
cursor text secret
last_synced_at ts
""", kind="conf", unique=[("tenant_id", "mailbox_id")])
t("email_webhook_events", """
mailbox_id uuid -> email_mailboxes
provider text!
idempotency_key text! uniq
event_type text!
payload json!
processed_at ts
""", kind="log", read="admin")
t("email_conversations", """
mailbox_id uuid! -> email_mailboxes
thread_id text!
subject text
prospect_id uuid -> prospects
campaign_id uuid -> prospect_campaigns
last_message_at ts
status text! =\'open\' in(open,pending,closed,archived)
""", unique=[("tenant_id", "mailbox_id", "thread_id")])
t("email_conversation_participants", """
conversation_id uuid! -> email_conversations cascade
email text!
name text
role text! in(from,to,cc,bcc)
""", kind="conf")
t("email_messages", """
conversation_id uuid! -> email_conversations
mailbox_id uuid! -> email_mailboxes
message_id_header text! # RFC 5322 Message-ID
in_reply_to text
references_header text
provider_message_id text
direction text! in(inbound,outbound)
from_email text!
to_emails text[]
cc_emails text[]
subject text
body_text text
body_html_storage_path text
sent_at ts
received_at ts
prospect_id uuid -> prospects
campaign_id uuid -> prospect_campaigns
""", unique=[("tenant_id", "mailbox_id", "message_id_header")])
t("email_message_attachments", """
message_id uuid! -> email_messages cascade
filename text!
mime_type text
size_bytes bigint
storage_path text! # bucket privé Supabase Storage
""")
t("email_message_events", """
message_id uuid! -> email_messages
event_type text! in(opened,clicked,replied,forwarded,flagged)
occurred_at ts!
""", kind="log")
t("email_delivery_events", """
message_id uuid -> email_messages
provider text!
event_type text! in(queued,sent,delivered,deferred,bounced,dropped,complained)
idempotency_key text uniq
details json
""", kind="log")
t("email_reply_classifications", """
message_id uuid! -> email_messages
category text! in(interested,not_interested,out_of_office,unsubscribe,question,bounce,other)
confidence num
model_code text
""", kind="log")
t("email_reply_suggestions", """
message_id uuid! -> email_messages
body text!
model_code text
""", kind="log")
t("email_reply_drafts", """
message_id uuid! -> email_messages
author_id uuid -> auth.users setnull
body text!
status text! =\'draft\' in(draft,approved,sent,discarded)
""")
t("email_suppression_events", """
email text!
reason text! in(bounce,complaint,unsubscribe,manual)
source_message_id uuid -> email_messages
""", kind="log")
t("email_thread_associations", """
conversation_id uuid! -> email_conversations
entity_type text!
entity_id uuid!
""", kind="conf")
t("email_sync_runs", """
mailbox_id uuid! -> email_mailboxes
execution_id uuid
status text! in(running,succeeded,failed)
messages_synced int! =0
error_message text
""", kind="log")
t("email_provider_errors", """
mailbox_id uuid -> email_mailboxes
error_code text
error_message text!
""", kind="log")
t("email_commercial_assignments", """
conversation_id uuid! -> email_conversations
user_id uuid! -> auth.users
assigned_at ts! =now()
unassigned_at ts
""", kind="log")

# ───────────────────────── N. GROWTH INTELLIGENCE ─────────────────────────
t = domain("N. Growth Intelligence", "intelligence")
t("growth_intelligence_events", "product_id uuid -> products\nevent_type text!\nsource text\ndata json! =\'{}\'", kind="log")
t("growth_intelligence_insights", "product_id uuid -> products\ntitle text!\nbody text\nconfidence num\nstatus text! =\'new\' in(new,acknowledged,dismissed)")
t("growth_opportunities", "product_id uuid -> products\ntitle text!\ndescription text\nimpact_score num\nstatus text! =\'open\' in(open,planned,done,dismissed)")
t("growth_opportunity_evidence", "opportunity_id uuid! -> growth_opportunities cascade\nsource text\ndata json", kind="log")
t("growth_strategy_plans", "product_id uuid -> products\ntitle text!\nhorizon text\nstatus text! =\'draft\' in(draft,active,completed,archived)\nplan json! =\'{}\'")
t("growth_strategy_actions", "plan_id uuid! -> growth_strategy_plans cascade\ntitle text!\nowner_user_id uuid -> auth.users setnull\ndue_date date\nstatus text! =\'todo\' in(todo,doing,done,cancelled)")
t("growth_predictions", "product_id uuid -> products\nmetric text!\nhorizon_days int!\npredicted_value num!\nmodel_version text", kind="log")
t("growth_prediction_evaluations", "prediction_id uuid! -> growth_predictions\nactual_value num\nerror num", kind="log")
t("growth_experiments", "product_id uuid -> products\nname text!\nhypothesis text\nstatus text! =\'draft\' in(draft,running,completed,stopped)\nstarted_at ts\nended_at ts")
t("growth_experiment_variants", "experiment_id uuid! -> growth_experiments cascade\nname text!\nallocation_pct num")
t("growth_experiment_results", "variant_id uuid! -> growth_experiment_variants\nmetric text!\nvalue num\nsignificance num", kind="log")
t("growth_learning_events", "source text!\nlesson text!\ndata json", kind="log")
t("growth_recommendations", "product_id uuid -> products\ntitle text!\nbody text\npriority int! =3\nstatus text! =\'open\' in(open,accepted,rejected,done)")
t("growth_recommendation_feedback", "recommendation_id uuid! -> growth_recommendations\nuser_id uuid -> auth.users setnull\nrating int\ncomment text", kind="log")
t("growth_decision_logs", "decision text!\nrationale text\ndecided_by uuid -> auth.users setnull\ninputs json", kind="log")
t("growth_proactive_alerts", "product_id uuid -> products\nmessage text!\nseverity text! =\'info\' in(info,warning,critical)\nacknowledged_at ts", kind="log")
t("growth_intelligence_snapshots", "product_id uuid -> products\ndata json!", kind="log")

# ───────────────────────── O. THOR ─────────────────────────
t = domain("O. THOR", "thor")
t("thor_conversations", "user_id uuid! -> auth.users\nproduct_id uuid -> products\ntitle text\nstatus text! =\'active\' in(active,archived)")
t("thor_messages", "conversation_id uuid! -> thor_conversations\nrole text! in(user,assistant,tool,system)\ncontent text!\nmodel_code text\ninput_tokens int\noutput_tokens int", kind="log")
t("thor_tool_executions", "message_id uuid! -> thor_messages\ntool_name text!\nexecution_id uuid\nstatus text! in(succeeded,failed,denied)\ninput_summary json\noutput_summary json", kind="log")
t("thor_memory", "user_id uuid -> auth.users cascade\nproduct_id uuid -> products\nmemory_type text! in(fact,preference,context,summary)\ncontent text!\nembedding vec\nexpires_at ts")
t("thor_memory_sources", "memory_id uuid! -> thor_memory cascade\nsource_type text!\nsource_id uuid", kind="log")
t("thor_feedback", "message_id uuid! -> thor_messages\nuser_id uuid -> auth.users setnull\nrating int in(-1,1)\ncomment text", kind="log")
