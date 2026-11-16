"""Domains A–D: identity, licensing, authorizations, connectors."""
from dsl import domain

# ───────────────────────── A. IDENTITÉ ET UTILISATEURS ─────────────────────────
t = domain("A. Identité et utilisateurs", "accounts")
t("user_profiles", """
email text!
full_name text
avatar_url text
locale text! =\'fr\' in(fr,en)
theme text! =\'system\' in(light,dark,system)
timezone text! =\'Europe/Paris\'
platform_role_code text # code from platform_roles, null for ordinary users
status text! =\'active\' in(active,suspended,disabled)
email_verified_at ts
mfa_enabled bool! =false
last_login_at ts
""", kind="gbiz", read="self", pk_ref="auth.users",
  comment="Profil applicatif 1-1 avec auth.users (identité Supabase).")

t = domain("A. Identité et utilisateurs", "tenants")
t("tenants", """
name text!
slug text! uniq
legal_name text
country_code text
status text! =\'active\' in(provisioning,active,suspended,archived)
suspended_reason text
suspended_at ts
owner_user_id uuid -> auth.users setnull
is_demo bool! =false
metadata json! =\'{}\' # free-form display metadata, never secrets
""", kind="gbiz", read="tenant_row", comment="Organisation cliente (tenant).")
t("tenant_domains", """
domain text! uniq
is_primary bool! =false
verification_status text! =\'pending\' in(pending,verified,failed)
verification_token text secret
verified_at ts
""", kind="conf")
t("tenant_settings", """
key text! uniq
value json!
description text
""", kind="conf", comment="Paramètres clé/valeur du tenant. value: JSON documenté par clé (docs/database/DATA_DICTIONARY.md).")
t("tenant_owner_registry", """
tenant_id uuid! -> tenants
user_id uuid! -> auth.users
source text! in(demo_signup,pilot_created,transfer)
created_at ts! =now()
""", kind="ref", read="pilot",
  comment="Garantit une seule création automatique de tenant propriétaire par utilisateur DEMO.")

t = domain("A. Identité et utilisateurs", "memberships")
t("tenant_members", """
user_id uuid! -> auth.users
display_name text
job_title text
status text! =\'active\' in(invited,active,suspended,removed)
joined_at ts! =now()
removed_at ts
last_active_at ts
""", unique=[("tenant_id", "user_id")], comment="Appartenance d'un utilisateur à un tenant.")
t("platform_roles", """
code text! uniq
name text!
description text
is_system bool! =true
""", kind="ref", comment="Rôles plateforme (PILOTE, SUPPORT…).")
t("tenant_roles", """
tenant_id uuid -> tenants cascade # null = rôle système partagé
code text!
name text!
description text
is_system bool! =false
""", kind="ref", read="member_or_shared", unique=[("tenant_id", "code")], comment="Rôles tenant (système si tenant_id null).")
t("tenant_memberships", """
member_id uuid! -> tenant_members cascade
role_id uuid! -> tenant_roles
valid_from ts! =now()
valid_until ts
granted_reason text
""", unique=[("tenant_id", "member_id", "role_id")], comment="Attribution de rôles à un membre.")
t("tenant_member_activity_logs", """
member_id uuid -> tenant_members
user_id uuid -> auth.users
activity text!
metadata json! =\'{}\'
""", kind="log", read="admin")

t = domain("A. Identité et utilisateurs", "permissions")
t("permissions", """
code text! uniq # ex: products.write
module_code text!
name text!
description text
scope text! =\'tenant\' in(platform,tenant)
""", kind="ref")
t("role_permissions", """
role_id uuid! -> tenant_roles cascade
permission_id uuid! -> permissions cascade
platform_role_id uuid -> platform_roles cascade
""", kind="ref", unique=[("role_id", "permission_id")])
t("user_permissions", """
member_id uuid! -> tenant_members cascade
permission_id uuid! -> permissions
effect text! =\'allow\' in(allow,deny)
expires_at ts
reason text
""", unique=[("tenant_id", "member_id", "permission_id")], read="admin")

t = domain("A. Identité et utilisateurs", "accounts")
t("user_sessions", """
user_id uuid! -> auth.users cascade
tenant_id uuid -> tenants cascade
supabase_session_id uuid
ip_address inet
user_agent text
started_at ts! =now()
last_seen_at ts
revoked_at ts
revoked_reason text
created_at ts! =now()
""", kind="ref", read="self", comment="Sessions applicatives (traçabilité / révocation).")
t("identity_providers", """
code text! uniq
name text!
protocol text! in(saml,oidc,oauth)
is_enabled bool! =true
""", kind="ref")
t("tenant_sso_configurations", """
identity_provider_id uuid! -> identity_providers
supabase_sso_provider_id uuid
metadata_url text
entity_id text
client_id text
client_secret_ref text secret # référence Vault, jamais la valeur
enforce_sso bool! =false
status text! =\'draft\' in(draft,active,disabled)
""", kind="conf", read="admin")
t("tenant_sso_group_mappings", """
sso_configuration_id uuid! -> tenant_sso_configurations cascade
external_group text!
role_id uuid! -> tenant_roles
""", kind="conf", read="admin", unique=[("tenant_id", "sso_configuration_id", "external_group")])

t = domain("A. Identité et utilisateurs", "invitations")
t("tenant_invitations", """
email text!
role_id uuid! -> tenant_roles
invited_by uuid -> auth.users setnull
status text! =\'pending\' in(pending,accepted,revoked,expired)
expires_at ts!
accepted_at ts
accepted_user_id uuid -> auth.users setnull
revoked_at ts
message text
""", read="admin", index=[("tenant_id", "email")])
t("invitation_tokens", """
invitation_id uuid! -> tenant_invitations cascade
token_hash text! uniq secret # SHA-256 du jeton, jamais le jeton en clair
expires_at ts!
used_at ts
created_at ts! =now()
""", kind="ref", read="none")
t("tenant_invitation_events", """
invitation_id uuid! -> tenant_invitations cascade
event_type text! in(created,sent,resent,opened,accepted,revoked,expired,failed)
actor_user_id uuid -> auth.users setnull
metadata json! =\'{}\'
""", kind="log", read="admin")

# ───────────────────────── B. LICENCES ─────────────────────────
t = domain("B. Licences", "licensing")
t("subscription_plans", """
code text! uniq in(DEMO,STARTER,GROWTH,GROWTH_ENTREPRISE)
name text!
description text
is_trial bool! =false
trial_duration_hours int
price_monthly_cents int
price_yearly_cents int
currency text! =\'EUR\'
is_active bool! =true
sort_order int! =0
""", kind="ref")
t("subscription_plan_features", """
plan_id uuid! -> subscription_plans cascade
feature_id uuid! -> platform_module_features cascade
enabled bool! =true
""", kind="ref", unique=[("plan_id", "feature_id")])
t("subscription_plan_quotas", """
plan_id uuid! -> subscription_plans cascade
quota_code text! # ex: scheduler.configurations, products.max, ai.tokens.monthly
limit_value bigint # null = illimité
period text! =\'none\' in(none,day,month,year)
""", kind="ref", unique=[("plan_id", "quota_code")])
t("tenant_subscriptions", """
plan_id uuid! -> subscription_plans
status text! =\'active\' in(trialing,active,past_due,suspended,cancelled,expired)
started_at ts! =now()
current_period_start ts
current_period_end ts
trial_ends_at ts
cancelled_at ts
external_customer_id text
external_subscription_id text
""", read="admin", index=[("tenant_id", "status")])
t("tenant_license_overrides", """
subscription_id uuid -> tenant_subscriptions
override_type text! in(feature,quota,module,agent)
target_code text!
value json! # {"enabled":bool} | {"limit":int,"period":str}
reason text!
expires_at ts
""", kind="conf", read="admin")
t("tenant_license_feature_access", """
feature_id uuid! -> platform_module_features
enabled bool!
source text! in(plan,override,trial)
""", kind="conf", unique=[("tenant_id", "feature_id")])
t("tenant_license_quotas", """
quota_code text!
limit_value bigint
period text! =\'none\' in(none,day,month,year)
used_value bigint! =0
period_start ts
source text! in(plan,override,trial)
""", kind="conf", unique=[("tenant_id", "quota_code")])
t("tenant_subscription_history", """
subscription_id uuid! -> tenant_subscriptions
event_type text! in(created,upgraded,downgraded,renewed,suspended,reactivated,cancelled,expired,trial_extended)
from_plan_id uuid -> subscription_plans
to_plan_id uuid -> subscription_plans
actor_user_id uuid -> auth.users setnull
reason text
""", kind="log", read="admin")
t("subscription_invoices", """
subscription_id uuid -> tenant_subscriptions
number text! uniq
status text! =\'draft\' in(draft,open,paid,void,uncollectible)
amount_cents int!
currency text! =\'EUR\'
issued_at ts
due_at ts
paid_at ts
pdf_storage_path text
external_invoice_id text
""", read="admin")
t("subscription_payments", """
invoice_id uuid -> subscription_invoices
amount_cents int!
currency text! =\'EUR\'
status text! in(pending,succeeded,failed,refunded)
provider text!
external_payment_id text
paid_at ts
""", read="admin")
t("subscription_payment_events", """
payment_id uuid -> subscription_payments
provider text!
idempotency_key text! uniq
event_type text!
payload json! # payload fournisseur expurgé des secrets
""", kind="log", read="pilot")
t("subscription_usage", """
quota_code text!
period_start ts!
period_end ts!
used_value bigint! =0
""", kind="conf", unique=[("tenant_id", "quota_code", "period_start")])
t("subscription_usage_alerts", """
quota_code text!
threshold_pct int! in(50,80,90,100)
triggered_at ts! =now()
notified bool! =false
""", kind="log", read="admin")
t("trial_activations", """
plan_id uuid! -> subscription_plans
user_id uuid! -> auth.users
activated_at ts! =now()
expires_at ts!
status text! =\'active\' in(active,converted,expired,cancelled)
""", read="admin", unique=[("tenant_id", "plan_id")])
t("trial_conversion_events", """
trial_id uuid! -> trial_activations
event_type text! in(converted,expired,cancelled,reminder_sent)
to_plan_id uuid -> subscription_plans
""", kind="log", read="admin")
t("trial_notification_logs", """
trial_id uuid! -> trial_activations
channel text! in(email,in_app)
template_code text!
sent_at ts! =now()
status text! in(sent,failed)
""", kind="log", read="admin")
t("tenant_trial_extensions", """
trial_id uuid! -> trial_activations
extended_by_hours int!
previous_expires_at ts!
new_expires_at ts!
granted_by uuid -> auth.users setnull
reason text!
""", kind="log", read="admin")

# ───────────────────────── C. AUTORISATIONS ─────────────────────────
t = domain("C. Autorisations", "permissions")
t("platform_modules", """
code text! uniq
name text!
description text
category text
is_core bool! =false
is_enabled bool! =true
sort_order int! =0
""", kind="ref")
t("platform_module_features", """
module_id uuid! -> platform_modules cascade
code text! uniq
name text!
description text
""", kind="ref")
t("tenant_module_authorizations", """
module_id uuid! -> platform_modules
status text! =\'enabled\' in(enabled,disabled,suspended)
granted_by uuid -> auth.users setnull
reason text
expires_at ts
""", kind="conf", unique=[("tenant_id", "module_id")])
t("tenant_feature_authorizations", """
feature_id uuid! -> platform_module_features
status text! =\'enabled\' in(enabled,disabled)
granted_by uuid -> auth.users setnull
reason text
""", kind="conf", unique=[("tenant_id", "feature_id")])
t("ai_agents_registry", """
code text! uniq
name text!
module_id uuid -> platform_modules
description text
default_model_code text
is_enabled bool! =true
""", kind="gbiz", comment="Catalogue global des agents IA (versionné).")
t("tenant_ai_agent_authorizations", """
agent_id uuid! -> ai_agents_registry
status text! =\'enabled\' in(enabled,disabled,suspended)
granted_by uuid -> auth.users setnull
reason text
""", kind="conf", unique=[("tenant_id", "agent_id")])
t("tenant_agent_permissions", """
agent_id uuid! -> ai_agents_registry
action_code text!
effect text! =\'allow\' in(allow,deny)
requires_approval bool! =false
""", kind="conf", unique=[("tenant_id", "agent_id", "action_code")])
t("tenant_agent_product_scopes", """
agent_id uuid! -> ai_agents_registry
product_id uuid! -> products cascade
""", kind="conf", unique=[("tenant_id", "agent_id", "product_id")])
t("tenant_agent_quotas", """
agent_id uuid! -> ai_agents_registry
quota_code text!
limit_value bigint
period text! =\'month\' in(none,day,month,year)
used_value bigint! =0
""", kind="conf", unique=[("tenant_id", "agent_id", "quota_code")])
t("tenant_ai_budgets", """
period text! =\'month\' in(day,month,year)
budget_cents bigint!
spent_cents bigint! =0
hard_limit bool! =true
alert_threshold_pct int! =80
""", kind="conf", read="admin", unique=[("tenant_id", "period")])
t("tenant_usage_events", """
module_code text!
usage_code text!
quantity num! =1
unit text
cost_cents num
product_id uuid -> products
idempotency_key text uniq
""", kind="log", read="admin", partition=False)
t("authorization_audit_logs", """
actor_user_id uuid -> auth.users setnull
target_type text! in(module,feature,agent,quota,permission,role,connector)
target_id uuid
action text! in(grant,revoke,suspend,resume,update)
before_data json
after_data json
reason text
""", kind="glog", read="admin")
t("tenant_license_requests", """
requested_by uuid -> auth.users setnull
request_type text! in(module,feature,agent,quota,plan_upgrade)
target_code text!
message text
status text! =\'pending\' in(pending,approved,rejected,cancelled)
decided_by uuid -> auth.users setnull
decided_at ts
decision_reason text
""", read="admin")
t("tenant_agent_suspensions", """
agent_id uuid! -> ai_agents_registry
suspended_by uuid -> auth.users setnull
reason text!
suspended_at ts! =now()
lifted_at ts
lifted_by uuid -> auth.users setnull
""", read="admin")

# ───────────────────────── D. CONNECTEURS ─────────────────────────
t = domain("D. Connecteurs", "integrations")
t("connector_providers", """
code text! uniq
name text!
category text! in(analytics,crm,email,social,seo,cms,ads,storage,ai,other)
auth_type text! in(oauth2,api_key,basic,none,webhook)
docs_url text
is_enabled bool! =true
""", kind="ref")
t("connector_capabilities", """
provider_id uuid! -> connector_providers cascade
code text!
name text!
direction text! in(read,write,bidirectional,webhook)
""", kind="ref", unique=[("provider_id", "code")])
t("connector_global_configurations", """
provider_id uuid! -> connector_providers uniq
client_id text
client_secret_ref text secret # référence Supabase Vault
redirect_uri text
settings json! =\'{}\'
is_enabled bool! =true
""", kind="gbiz", read="pilot")
t("tenant_connector_authorizations", """
provider_id uuid! -> connector_providers
status text! =\'enabled\' in(enabled,disabled,suspended)
granted_by uuid -> auth.users setnull
reason text
""", kind="conf", unique=[("tenant_id", "provider_id")])
t("tenant_connector_accounts", """
provider_id uuid! -> connector_providers
product_id uuid -> products
external_account_id text
display_name text!
status text! =\'pending\' in(pending,connected,error,disconnected,revoked)
connected_by uuid -> auth.users setnull
connected_at ts
last_sync_at ts
""", index=[("tenant_id", "provider_id")])
t("tenant_connector_credentials", """
account_id uuid! -> tenant_connector_accounts cascade
credential_type text! in(oauth_token,api_key,basic,webhook_secret)
vault_secret_id uuid secret # id Supabase Vault (chiffré au repos)
masked_hint text # ex: ••••abcd
expires_at ts
rotated_at ts
""", kind="conf", read="none")
t("tenant_connector_scopes", """
account_id uuid! -> tenant_connector_accounts cascade
scope text!
granted bool! =true
""", kind="conf", unique=[("tenant_id", "account_id", "scope")])
t("connector_health_checks", """
account_id uuid -> tenant_connector_accounts cascade
status text! in(healthy,degraded,down,not_configured,unknown)
latency_ms int
error_message text
checked_at ts! =now()
""", kind="log")
t("connector_sync_runs", """
account_id uuid! -> tenant_connector_accounts
execution_id uuid
status text! in(queued,running,succeeded,failed,cancelled)
started_at ts
completed_at ts
records_read int! =0
records_written int! =0
error_message text
""", kind="log")
t("connector_error_logs", """
account_id uuid -> tenant_connector_accounts
sync_run_id uuid -> connector_sync_runs
error_code text
error_message text!
details json
""", kind="log")
t("connector_webhooks", """
account_id uuid! -> tenant_connector_accounts cascade
event_type text!
endpoint_path text!
secret_ref text secret
status text! =\'active\' in(active,disabled)
""", kind="conf")
t("connector_usage_events", """
account_id uuid -> tenant_connector_accounts
operation text!
quantity int! =1
idempotency_key text uniq
""", kind="log", read="admin")
t("connector_audit_logs", """
account_id uuid -> tenant_connector_accounts
actor_user_id uuid -> auth.users setnull
action text! in(connect,disconnect,reauthorize,rotate_secret,update_scopes,authorize,revoke)
details json
""", kind="log", read="admin")
