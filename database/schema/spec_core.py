"""Domains E, M, P, Q, R, S and the cross-cutting traceability tables."""
from dsl import domain

# ───────────────────────── E. PRODUITS ET SITES WEB ─────────────────────────
t = domain("E. Produits et sites web", "products")
t("products", """
name text!
slug text! uniq
description text
category text
status text! =\'active\' in(draft,active,paused,archived)
primary_domain text
logo_storage_path text
""")
t("product_domains", """
product_id uuid! -> products cascade
domain text!
is_primary bool! =false
""", kind="conf", unique=[("tenant_id", "product_id", "domain")])
t("product_settings", """
product_id uuid! -> products cascade
key text!
value json!
""", kind="conf", unique=[("tenant_id", "product_id", "key")])
t("product_goals", """
product_id uuid! -> products cascade
goal_type text! in(traffic,leads,revenue,visibility,engagement,other)
title text!
target_value num
unit text
due_date date
status text! =\'active\' in(active,achieved,abandoned)
""")
t("product_audiences", """
product_id uuid! -> products cascade
name text!
description text
attributes json! =\'{}\' # {"geo":[],"industries":[],"company_size":[]}
""")
t("product_personas", """
product_id uuid! -> products cascade
audience_id uuid -> product_audiences setnull
name text!
role text
pains text[]
goals text[]
profile json! =\'{}\'
""")
t("product_competitors", """
product_id uuid! -> products cascade
name text!
website_url text
notes text
""")
t("product_integrations", """
product_id uuid! -> products cascade
connector_account_id uuid! -> tenant_connector_accounts cascade
purpose text
""", kind="conf", unique=[("tenant_id", "product_id", "connector_account_id")])
t("product_business_context", """
product_id uuid! -> products cascade uniq
value_proposition text
positioning text
pricing_model text
key_messages text[]
context json! =\'{}\' # synthèse structurée utilisée par les agents
""")
t("product_business_context_sources", """
context_id uuid! -> product_business_context cascade
source_type text! in(website,document,manual,connector,ai_extraction)
source_ref text
storage_path text
extracted_at ts
""")

t = domain("E. Produits et sites web", "websites")
t("websites", """
product_id uuid -> products setnull
url text!
name text
cms text
status text! =\'active\' in(active,paused,archived)
""", unique=[("tenant_id", "url")])
t("website_pages", """
website_id uuid! -> websites cascade
url text!
path text!
title text
meta_description text
status_code int
content_hash text
last_crawled_at ts
""", unique=[("tenant_id", "website_id", "path")])
t("website_technologies", """
website_id uuid! -> websites cascade
name text!
category text
version text
detected_at ts! =now()
""", kind="conf", unique=[("tenant_id", "website_id", "name")])
t("website_scans", """
website_id uuid! -> websites
scan_type text! in(crawl,technology,performance,security,full)
status text! =\'queued\' in(queued,running,succeeded,failed,cancelled)
execution_id uuid
started_at ts
completed_at ts
pages_scanned int! =0
requested_by uuid -> auth.users setnull
""", kind="log")
t("website_scan_results", """
scan_id uuid! -> website_scans cascade
page_id uuid -> website_pages setnull
result_type text!
severity text in(info,low,medium,high,critical)
data json! =\'{}\'
""", kind="log")

# ───────────────────────── M. SCHEDULER ET WORKFLOWS ─────────────────────────
t = domain("M. Scheduler et workflows", "scheduler")
t("tenant_schedulers", """
product_id uuid -> products
name text!
description text
timezone text! =\'UTC\'
status text! =\'active\' in(active,paused,disabled)
""")
t("scheduler_retry_policies", """
tenant_id uuid -> tenants cascade
name text!
max_attempts int! =3
backoff_seconds int! =60
backoff_multiplier num! =2
max_backoff_seconds int! =3600
""", kind="ref", read="member_or_shared", unique=[("tenant_id", "name")])
t("scheduler_tasks", """
scheduler_id uuid! -> tenant_schedulers cascade
name text!
task_type text! # code tâche Celery / module
cron_expression text
interval_seconds int
payload json! =\'{}\'
retry_policy_id uuid -> scheduler_retry_policies
status text! =\'active\' in(active,paused,disabled)
next_run_at ts
last_run_at ts
""", index=[("status", "next_run_at")])
t("scheduler_task_dependencies", """
task_id uuid! -> scheduler_tasks cascade
depends_on_task_id uuid! -> scheduler_tasks cascade
condition text! =\'success\' in(success,completion,failure)
""", kind="conf", unique=[("tenant_id", "task_id", "depends_on_task_id")])
t("scheduler_execution_runs", """
task_id uuid! -> scheduler_tasks
execution_id uuid! uniq
celery_task_id text
status text! in(queued,running,succeeded,failed,cancelled,retrying,dead_letter)
attempt int! =1
started_at ts
completed_at ts
duration_ms int
error_message text
triggered_by text! =\'schedule\' in(schedule,manual,dependency,retry)
""", kind="log", index=[("task_id", "created_at")])
t("scheduler_execution_steps", """
run_id uuid! -> scheduler_execution_runs cascade
step_name text!
status text! in(pending,running,succeeded,failed,skipped)
started_at ts
completed_at ts
output_summary json
""", kind="log")
t("scheduler_execution_metrics", """
run_id uuid! -> scheduler_execution_runs cascade
metric text!
value num!
""", kind="log")
t("scheduler_resource_locks", """
resource_key text!
locked_by text!
execution_id uuid
expires_at ts!
created_at ts! =now()
""", kind="conf", read="admin", unique=[("tenant_id", "resource_key")])
t("scheduler_approval_policies", """
task_type text!
requires_approval bool! =true
approver_role_id uuid -> tenant_roles
""", kind="conf", unique=[("tenant_id", "task_type")])
t("scheduler_quotas", """
quota_code text!
limit_value int!
used_value int! =0
""", kind="conf", unique=[("tenant_id", "quota_code")])
t("scheduled_notifications", """
notification_template_code text!
recipient_user_id uuid -> auth.users cascade
send_at ts!
payload json! =\'{}\'
status text! =\'pending\' in(pending,sent,cancelled,failed)
""")
t("growth_workflow_definitions", """
product_id uuid -> products
name text!
description text
status text! =\'draft\' in(draft,active,archived)
definition json! =\'{}\' # graphe {nodes:[],edges:[]}
""")
t("growth_workflow_nodes", """
workflow_id uuid! -> growth_workflow_definitions cascade
node_key text!
node_type text!
config json! =\'{}\'
position int! =0
""", kind="conf", unique=[("tenant_id", "workflow_id", "node_key")])
t("growth_workflow_executions", """
workflow_id uuid! -> growth_workflow_definitions
workflow_execution_id uuid! uniq
status text! in(queued,running,succeeded,failed,cancelled,waiting_approval)
started_at ts
completed_at ts
triggered_by uuid -> auth.users setnull
error_message text
""", kind="log")
t("growth_workflow_execution_steps", """
execution_id uuid! -> growth_workflow_executions cascade
node_key text!
status text! in(pending,running,succeeded,failed,skipped)
started_at ts
completed_at ts
output_summary json
error_message text
""", kind="log")

# ───────────────────────── P. REPORTING ─────────────────────────
t = domain("P. Reporting", "reporting")
t("tenant_reporting_snapshots", """
product_id uuid -> products
period_start date!
period_end date!
metrics json! # {"metric_code": value}
""", kind="log")
t("execution_reports", """
product_id uuid -> products
execution_id uuid
title text!
summary text
status text! in(draft,final)
storage_path text
""")
t("execution_report_metrics", """
report_id uuid! -> execution_reports cascade
metric text!
value num
unit text
""", kind="log")
t("execution_error_logs", """
execution_id uuid
module text!
error_code text
error_message text!
details json
""", kind="log")
t("report_schedules", """
product_id uuid -> products
report_type text!
cron_expression text!
recipients text[]
format text! =\'pdf\' in(pdf,csv,xlsx,html)
status text! =\'active\' in(active,paused)
""", kind="conf")
t("report_exports", """
report_id uuid -> execution_reports
export_job_id uuid -> export_jobs
format text! in(pdf,csv,xlsx,html)
storage_path text
""", kind="log")
t("analytics_sources", """
product_id uuid -> products
connector_account_id uuid -> tenant_connector_accounts
source_type text! in(ga4,search_console,matomo,plausible,custom)
name text!
""", kind="conf")
t("analytics_snapshots", """
source_id uuid! -> analytics_sources
period_start date!
period_end date!
data json!
""", kind="log")
t("analytics_metrics", """
source_id uuid! -> analytics_sources
metric text!
dimension text
date date!
value num!
""", kind="log", index=[("source_id", "metric", "date")])

# ───────────────────────── Q. NOTIFICATIONS ─────────────────────────
t = domain("Q. Notifications", "notifications")
t("notification_templates", """
code text! uniq
channel text! in(email,in_app,sms,webhook,slack)
locale text! =\'fr\'
subject text
body text!
""", kind="gbiz")
t("notification_preferences", """
user_id uuid! -> auth.users cascade
category text!
channel text! in(email,in_app,sms,webhook,slack)
enabled bool! =true
""", kind="conf", read="self", unique=[("tenant_id", "user_id", "category", "channel")])
t("notifications", """
user_id uuid -> auth.users cascade
category text!
title text!
body text
link text
severity text! =\'info\' in(info,success,warning,error)
read_at ts
""", kind="log", read="self", index=[("user_id", "read_at")])
t("notification_deliveries", """
notification_id uuid! -> notifications cascade
channel text!
status text! in(queued,sent,delivered,failed,bounced)
provider text
""", kind="log", read="admin")
t("notification_attempts", """
delivery_id uuid! -> notification_deliveries cascade
attempt int!
status text! in(sent,failed)
error_message text
""", kind="log", read="admin")
t("notification_provider_events", """
delivery_id uuid -> notification_deliveries
provider text!
idempotency_key text! uniq
event_type text!
payload json!
""", kind="glog")

# ───────────────────────── R. SYSTEM HEALTH ─────────────────────────
t = domain("R. System Health", "system_health")
t("system_services", """
code text! uniq
name text!
category text! in(database,auth,storage,api,cache,queue,worker,scheduler,connector,ai_provider,infrastructure,configuration)
is_critical bool! =false
is_enabled bool! =true
""", kind="ref", read="pilot")
t("system_health_checks", """
service_id uuid! -> system_services cascade
code text! uniq
name text!
check_type text!
interval_seconds int! =300
timeout_ms int! =5000
is_enabled bool! =true
""", kind="ref", read="pilot")
t("system_health_results", """
check_id uuid! -> system_health_checks
status text! in(healthy,degraded,down,not_configured,unknown,checking)
latency_ms int
error_message text
recommendation text
details json
""", kind="glog", index=[("check_id", "created_at")])
t("system_incidents", """
service_id uuid -> system_services
title text!
severity text! in(sev1,sev2,sev3,sev4)
status text! =\'open\' in(open,investigating,mitigated,resolved)
started_at ts! =now()
resolved_at ts
summary text
""", kind="gbiz", read="pilot")
t("system_alerts", """
service_id uuid -> system_services
incident_id uuid -> system_incidents
severity text! in(info,warning,critical)
message text!
acknowledged_at ts
acknowledged_by uuid -> auth.users setnull
""", kind="glog")
t("system_test_runs", """
triggered_by uuid -> auth.users setnull
suite text!
status text! in(running,passed,failed,error)
started_at ts! =now()
completed_at ts
passed int! =0
failed int! =0
""", kind="glog")
t("system_test_results", """
run_id uuid! -> system_test_runs
test_name text!
status text! in(passed,failed,skipped,error)
duration_ms int
error_message text
""", kind="glog")
t("system_configuration_checks", """
key text!
status text! in(ok,missing,invalid,warning)
message text
""", kind="glog")
t("system_api_checks", """
endpoint text!
method text! =\'GET\'
status_code int
latency_ms int
status text! in(healthy,degraded,down)
""", kind="glog")
t("system_database_checks", """
check_name text!
status text! in(healthy,degraded,down)
value json
""", kind="glog")
t("system_infrastructure_snapshots", """
component text!
metrics json!
""", kind="glog")
t("system_error_events", """
service_code text
error_code text
message text!
stack_trace text
fingerprint text
request_id uuid
""", kind="glog", index=[("fingerprint",)])
t("system_audit_logs", """
actor_user_id uuid -> auth.users setnull
action text!
target text
details json
""", kind="glog")
t("application_logs", """
level text! in(debug,info,warning,error,critical)
logger text!
message text!
request_id uuid
execution_id uuid
context json
""", kind="glog", partition=True)

# ───────────────────────── S. FOURNISSEURS IA ─────────────────────────
t = domain("S. Fournisseurs IA", "ai_providers")
t("ai_providers", """
code text! uniq
name text!
base_url text
is_enabled bool! =true
""", kind="ref")
t("ai_models", """
provider_id uuid! -> ai_providers cascade
code text! uniq
name text!
context_window int
input_cost_per_mtok_cents num
output_cost_per_mtok_cents num
is_enabled bool! =true
""", kind="ref")
t("ai_provider_configurations", """
provider_id uuid! -> ai_providers
tenant_id uuid -> tenants cascade # null = configuration plateforme
api_key_ref text secret # référence Vault
settings json! =\'{}\'
is_enabled bool! =true
""", kind="gbiz", read="pilot", unique=[("tenant_id", "provider_id")])
t("ai_model_capabilities", """
model_id uuid! -> ai_models cascade
capability text! in(chat,vision,embedding,tools,json,image,audio,video)
""", kind="ref", unique=[("model_id", "capability")])
t("ai_prompt_templates", """
tenant_id uuid -> tenants cascade
code text!
name text!
template text!
variables json! =\'[]\'
model_code text
status text! =\'draft\' in(draft,active,archived)
""", kind="gbiz", read="member_or_shared", unique=[("tenant_id", "code")])
t("ai_execution_logs", """
agent_id uuid -> ai_agents_registry
model_id uuid -> ai_models
execution_id uuid
product_id uuid -> products
prompt_template_id uuid -> ai_prompt_templates
status text! in(succeeded,failed,timeout,cancelled)
input_tokens int
output_tokens int
cost_cents num
duration_ms int
error_message text
input_summary json
output_summary json
""", kind="log", read="admin")
t("ai_usage_events", """
model_id uuid -> ai_models
agent_id uuid -> ai_agents_registry
input_tokens int! =0
output_tokens int! =0
cost_cents num! =0
idempotency_key text uniq
""", kind="log", read="admin")
t("ai_cost_snapshots", """
period_start date!
period_end date!
cost_cents num!
breakdown json!
""", kind="log", read="admin")
t("ai_fallback_policies", """
tenant_id uuid -> tenants cascade
primary_model_id uuid! -> ai_models
fallback_model_id uuid! -> ai_models
priority int! =1
trigger_on text[]
""", kind="ref", read="pilot")

# ───────────────────────── TRAÇABILITÉ TRANSVERSALE ─────────────────────────
t = domain("Traçabilité", "audit")
t("audit_events", """
actor_user_id uuid
actor_type text! in(user,pilot,system,celery,agent,webhook,anonymous)
action text!
module text!
entity_type text
entity_id uuid
description text
before_data json # expurgé des secrets
after_data json
source text! =\'api\' in(api,admin,celery,webhook,sql,system,frontend)
status text! =\'success\' in(success,failure,denied)
ip_address inet
user_agent text
request_id uuid
""", kind="glog", read="admin", partition=True,
  index=[("entity_type", "entity_id"), ("request_id",), ("actor_user_id", "created_at"), ("module", "action")],
  comment="Niveau 3 — journal central des actions (immuable).")
t("activity_events", """
user_id uuid
product_id uuid
event_type text!
module text!
entity_type text
entity_id uuid
description text
metadata json! =\'{}\'
""", kind="log", partition=True, index=[("entity_type", "entity_id"), ("user_id", "created_at"), ("product_id", "created_at")],
  comment="Timeline chronologique des activités du tenant.")
t("execution_logs", """
module text!
operation text!
execution_id uuid!
parent_execution_id uuid
workflow_execution_id uuid
webhook_event_id uuid
request_id uuid
celery_task_id text
status text! in(queued,running,succeeded,failed,cancelled,retrying,dead_letter)
started_at ts
completed_at ts
duration_ms int
input_summary json
output_summary json
error_code text
error_message text
retry_count int! =0
cost_cents num
""", kind="glog", read="admin", partition=True, index=[("execution_id",), ("status", "created_at"), ("request_id",)],
  comment="Niveau 4 — opérations techniques (API, Celery, agents, fournisseurs).")
t("audit_log_corrections", """
table_name text!
row_id uuid!
before_data json!
after_data json!
reason text!
corrected_by uuid
""", kind="glog", read="pilot", comment="Corrections administratives exceptionnelles des journaux (elles-mêmes auditées).")
t("data_retention_policies", """
tenant_id uuid -> tenants cascade # null = politique plateforme par défaut
data_category text! # ex: audit_events, activity_events, personal_data
history_type text! in(business,history,activity,technical)
retention_days int!
archive_mode text! =\'none\' in(none,storage_export,cold_table)
deletion_rule text! =\'delete\' in(delete,anonymize,keep)
is_active bool! =true
""", kind="gbiz", read="member_or_shared", unique=[("tenant_id", "data_category")])
t("data_deletion_requests", """
requested_by uuid -> auth.users setnull
subject_user_id uuid
subject_email text
scope json! # {"entities":[...],"modules":[...]}
reason text!
status text! =\'pending\' in(pending,approved,rejected,running,completed,failed)
approved_by uuid -> auth.users setnull
approved_at ts
executed_at ts
result json
""", read="admin")
t("export_jobs", """
requested_by uuid -> auth.users setnull
export_type text!
scope json! =\'{}\'
format text! in(csv,json,xlsx,pdf)
status text! =\'queued\' in(queued,running,succeeded,failed,expired)
storage_path text
link_expires_at ts
result json
""", read="admin")
t("record_access_logs", """
user_id uuid
entity_type text!
entity_id uuid!
access_type text! in(read,export,download,reveal)
reason text
request_id uuid
""", kind="log", read="admin")
t("idempotency_keys", """
scope text!
key text!
response_hash text
expires_at ts!
""", kind="glog", read="none", unique=[("scope", "key")],
  comment="Clés d'idempotence pour webhooks, tâches et événements fournisseurs.")

t = domain("Traçabilité", "history")
t("entity_history", """
entity_type text!
entity_id uuid!
version_number int!
operation text! in(INSERT,UPDATE,DELETE,SOFT_DELETE,RESTORE)
previous_data json
current_data json
changed_fields text[]
changed_by uuid
actor_type text! =\'system\'
change_reason text
""", kind="glog", read="admin", unique=[("entity_type", "entity_id", "version_number")],
  comment="Niveau 2 — historique versionné (alimenté par trigger, contexte acteur fourni par Django).")
