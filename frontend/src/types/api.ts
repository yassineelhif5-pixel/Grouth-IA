export type HealthStatus = "healthy" | "degraded" | "down" | "not_configured" | "unknown" | "checking";

export interface TenantSummary {
  id: string;
  name: string;
  slug: string;
  status: string;
  is_demo: boolean;
  roles: string[];
  permissions: string[] | null;
  modules: string[] | null;
  subscription: { plan: string; status: string; trial_ends_at: string | null } | null;
}

export interface Me {
  user: { id: string; email: string; email_verified: boolean; aal: string; is_pilot: boolean };
  profile: { full_name: string | null; username: string | null; locale: "fr" | "en"; theme: "light" | "dark" | "system"; version_number: number } | null;
  tenants: TenantSummary[];
}

export interface Paged<T> {
  results: T[];
  has_more?: boolean;
  count?: number;
  next?: string | null;
}

export interface AuditEvent {
  id: string;
  tenant_id: string | null;
  created_at: string;
  actor_user_id: string | null;
  actor_type: string;
  action: string;
  module: string;
  entity_type: string | null;
  entity_id: string | null;
  description: string | null;
  before_data: Record<string, unknown> | null;
  after_data: Record<string, unknown> | null;
  source: string;
  status: string;
  request_id: string | null;
  correlation_id: string | null;
}

export interface EntityVersion {
  id: string;
  version_number: number;
  operation: string;
  changed_fields: string[] | null;
  previous_data?: Record<string, unknown> | null;
  current_data?: Record<string, unknown> | null;
  changed_by: string | null;
  change_reason: string | null;
  correlation_id: string | null;
  created_at: string;
}

export interface HealthCheck {
  service: string;
  service_name: string;
  category: string;
  code: string;
  name: string;
  status: HealthStatus | null;
  latency_ms: number | null;
  error_message: string | null;
  recommendation: string | null;
  checked_at: string | null;
}
