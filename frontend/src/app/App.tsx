import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { RequireAuth, RequirePermission, RequirePilot, RequireTenant } from "@/components/Guards";
import { HistoryCentre } from "@/features/HistoryCentre";
import { useTenant } from "@/hooks/useMe";
import { PilotLayout } from "@/layouts/PilotLayout";
import { TenantLayout } from "@/layouts/TenantLayout";
import { AcceptInvitationPage, HomeRedirect, LoginPage, MfaPage, OnboardingPage, ResetPasswordPage, SignupPage } from "@/pages/auth/AuthPages";
import * as P from "@/pages/pilot/PilotPages";
import * as T from "@/pages/tenant/TenantPages";

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
          <Route path="dashboard" element={<T.DashboardPage />} />
          <Route path="products" element={<RequirePermission perm="products.read" module="products"><T.ProductsPage /></RequirePermission>} />
          <Route path="websites" element={<RequirePermission perm="websites.read" module="websites"><T.WebsitesPage /></RequirePermission>} />
          <Route path="scheduler" element={<RequirePermission perm="scheduler.read" module="scheduler"><T.SchedulerPage /></RequirePermission>} />
          <Route path="connectors" element={<RequirePermission perm="connectors.read" module="connectors"><T.ConnectorsPage /></RequirePermission>} />
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
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
