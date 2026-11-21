import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { RequireAuth, RequirePermission, RequirePilot, RequireTenant } from "@/components/Guards";
import { HistoryCentre } from "@/features/HistoryCentre";
import { useTenant } from "@/hooks/useMe";
import { PilotLayout } from "@/layouts/PilotLayout";
import { TenantLayout } from "@/layouts/TenantLayout";
import { HuntPage } from "@/pages/tenant/HuntPage";
import { AcceptInvitationPage, HomeRedirect, LoginPage, MfaPage, OnboardingPage, ResetPasswordPage, SignupPage } from "@/pages/auth/AuthPages";
import * as P from "@/pages/pilot/PilotPages";
import * as M from "@/pages/tenant/ModulePages";
import * as T from "@/pages/tenant/TenantPages";
import { UsersPage } from "@/pages/tenant/UsersPage";
import * as V from "@/pages/tenant/VisibilityPages";
import { ConnectorsPage } from "@/pages/tenant/ConnectorsPage";

function TenantHistory() {
  const { tenantId, can } = useTenant();
  return <HistoryCentre scope="tenant" tenantId={tenantId} canExport={can("history.export")} />;
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/mfa" element={<RequireAuth><MfaPage /></RequireAuth>} />
        <Route path="/onboarding" element={<RequireAuth><OnboardingPage /></RequireAuth>} />
        <Route path="/invitations/accept" element={<RequireAuth><AcceptInvitationPage /></RequireAuth>} />
        <Route path="/" element={<RequireAuth><HomeRedirect /></RequireAuth>} />
        <Route path="/t/:tenantId" element={<RequireAuth><RequireTenant><TenantLayout /></RequireTenant></RequireAuth>}>
          <Route index element={<Navigate to="dashboard" replace />} />
          <Route path="dashboard" element={<V.HomeDashboardPage />} />
          <Route path="activity" element={<T.DashboardPage />} />
          <Route path="visibility" element={<RequirePermission perm="seo.read" module="seo"><V.ProgrammesPage /></RequirePermission>} />
          <Route path="visibility/new" element={<RequirePermission perm="seo.manage" module="seo"><V.ProgrammeWizardPage /></RequirePermission>} />
          <Route path="visibility/audit/:auditId" element={<RequirePermission perm="seo.read" module="seo"><V.AuditResultPage /></RequirePermission>} />
          <Route path="audit" element={<RequirePermission perm="seo.read" module="seo"><V.TenantAuditPage /></RequirePermission>} />
          <Route path="ai-visibility" element={<RequirePermission perm="geo.read" module="geo"><V.AiVisibilityPage /></RequirePermission>} />
          <Route path="users" element={<RequirePermission perm="members.read"><UsersPage /></RequirePermission>} />
          <Route path="products" element={<RequirePermission perm="products.read" module="products"><T.ProductsPage /></RequirePermission>} />
          <Route path="websites" element={<RequirePermission perm="websites.read" module="websites"><T.WebsitesPage /></RequirePermission>} />
          <Route path="scheduler" element={<RequirePermission perm="scheduler.read" module="scheduler"><M.SchedulerV2Page /></RequirePermission>} />
          <Route path="connectors" element={<RequirePermission perm="connectors.read"><ConnectorsPage /></RequirePermission>} />
          <Route path="seo" element={<RequirePermission perm="seo.read" module="seo"><M.SeoPage /></RequirePermission>} />
          <Route path="geo" element={<RequirePermission perm="geo.read" module="geo"><M.GeoPage /></RequirePermission>} />
          <Route path="content" element={<RequirePermission perm="content.read" module="content"><M.ContentPage /></RequirePermission>} />
          <Route path="pages" element={<RequirePermission perm="pages.read" module="pages"><M.PagesPage /></RequirePermission>} />
          <Route path="social" element={<RequirePermission perm="social.read" module="social"><M.SocialPage /></RequirePermission>} />
          <Route path="video" element={<RequirePermission perm="video.read" module="video"><M.VideoPage /></RequirePermission>} />
          <Route path="opportunities" element={<RequirePermission perm="opportunities.read" module="opportunities"><M.OpportunitiesPage /></RequirePermission>} />
          <Route path="prospects" element={<RequirePermission perm="prospects.read" module="prospects"><M.ProspectsPage /></RequirePermission>} />
          <Route path="hunt" element={<RequirePermission perm="prospects.read" module="prospects"><HuntPage /></RequirePermission>} />
          <Route path="campaigns" element={<RequirePermission perm="campaigns.read" module="prospects"><M.CampaignsPage /></RequirePermission>} />
          <Route path="email" element={<RequirePermission perm="email.read" module="email_center"><M.EmailCenterPage /></RequirePermission>} />
          <Route path="whatsapp" element={<RequirePermission perm="whatsapp.read" module="whatsapp"><M.WhatsAppPage /></RequirePermission>} />
          <Route path="crm" element={<RequirePermission perm="crm.read" module="crm"><M.CrmPage /></RequirePermission>} />
          <Route path="workflows" element={<RequirePermission perm="workflows.read" module="workflows"><M.WorkflowsPage /></RequirePermission>} />
          <Route path="intelligence" element={<RequirePermission perm="intelligence.read" module="intelligence"><M.IntelligencePage /></RequirePermission>} />
          <Route path="thor" element={<RequirePermission perm="thor.use" module="thor"><M.ThorPage /></RequirePermission>} />
          <Route path="approvals" element={<RequirePermission perm="approvals.decide"><M.ApprovalsPage /></RequirePermission>} />
          <Route path="reporting" element={<RequirePermission perm="reporting.read"><M.ReportingPage /></RequirePermission>} />
          <Route path="members" element={<RequirePermission perm="members.read"><T.MembersPage /></RequirePermission>} />
          <Route path="invitations" element={<RequirePermission perm="invitations.manage"><T.InvitationsPage /></RequirePermission>} />
          <Route path="history" element={<RequirePermission perm="history.read"><TenantHistory /></RequirePermission>} />
          <Route path="subscription" element={<RequirePermission perm="licenses.read"><T.SubscriptionPage /></RequirePermission>} />
          <Route path="settings" element={<T.SettingsPage />} />
        </Route>
        <Route path="/pilot" element={<RequireAuth><RequirePilot><PilotLayout /></RequirePilot></RequireAuth>}>
          <Route index element={<Navigate to="overview" replace />} />
          <Route path="overview" element={<P.PilotOverviewPage />} />
          <Route path="tenants" element={<P.PilotTenantsPage />} />
          <Route path="tenants/:tenantId" element={<P.PilotTenantDetailPage />} />
          <Route path="plans" element={<P.PilotPlansPage />} />
          <Route path="usage" element={<P.PilotUsagePage />} />
          <Route path="history" element={<P.PilotHistoryPage />} />
          <Route path="errors" element={<P.PilotErrorsPage />} />
          <Route path="health" element={<P.SystemHealthPage />} />
          <Route path="incidents" element={<P.PilotIncidentsPage />} />
          <Route path="ai" element={<P.PilotAIPage />} />
          <Route path="connectors" element={<P.PilotConnectorsPage />} />
          <Route path="global" element={<P.PilotGlobalPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
