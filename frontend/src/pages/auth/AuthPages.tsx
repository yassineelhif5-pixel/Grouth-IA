import { Alert, Anchor, Button, Center, Image, Paper, PasswordInput, PinInput, Stack, Text, TextInput, Title } from "@mantine/core";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { z } from "zod";

import { FullLoader } from "@/components/Guards";
import { Preferences } from "@/components/Preferences";
import { useMe } from "@/hooks/useMe";
import { api } from "@/services/api";
import { supabase } from "@/services/supabase";

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Center mih="100vh" p="md">
      <Paper withBorder shadow="sm" p="xl" w={420} radius="lg">
        <Stack>
          <Title order={3}>{title}</Title>
          {children}
          <Preferences />
        </Stack>
      </Paper>
    </Center>
  );
}

const credentials = z.object({ email: z.string().email(), password: z.string().min(10) });
type Credentials = z.infer<typeof credentials>;

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const loc = useLocation() as { state?: { from?: string } };
  const [error, setError] = useState<string | null>(null);
  const form = useForm<Credentials>({ resolver: zodResolver(credentials) });
  const submit = form.handleSubmit(async (v) => {
    setError(null);
    const { error: e } = await supabase.auth.signInWithPassword(v);
    if (e) return setError(e.message);
    const { data } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
    navigate(data?.nextLevel === "aal2" && data.currentLevel !== "aal2" ? "/mfa" : loc.state?.from ?? "/");
  });
  return (
    <Card title={t("auth.login")}>
      {error && <Alert color="red">{error}</Alert>}
      <form onSubmit={submit}>
        <Stack>
          <TextInput label={t("auth.email")} {...form.register("email")} error={form.formState.errors.email?.message} />
          <PasswordInput label={t("auth.password")} {...form.register("password")} error={form.formState.errors.password?.message} />
          <Button type="submit" loading={form.formState.isSubmitting}>{t("auth.login")}</Button>
        </Stack>
      </form>
      <Anchor component={Link} to="/reset-password" size="sm">{t("auth.forgot")}</Anchor>
      <Anchor component={Link} to="/signup" size="sm">{t("auth.signup")}</Anchor>
    </Card>
  );
}

export function SignupPage() {
  const { t } = useTranslation();
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<Credentials>({ resolver: zodResolver(credentials) });
  const submit = form.handleSubmit(async (v) => {
    const { error: e } = await supabase.auth.signUp({ ...v, options: { emailRedirectTo: `${window.location.origin}/onboarding` } });
    if (e) return setError(e.message);
    setDone(true);
  });
  return (
    <Card title={t("auth.signup")}>
      {done ? <Alert color="green">{t("auth.checkEmail")}</Alert> : (
        <form onSubmit={submit}>
          <Stack>
            {error && <Alert color="red">{error}</Alert>}
            <TextInput label={t("auth.email")} {...form.register("email")} error={form.formState.errors.email?.message} />
            <PasswordInput label={t("auth.password")} {...form.register("password")} error={form.formState.errors.password?.message} />
            <Button type="submit" loading={form.formState.isSubmitting}>{t("auth.signup")}</Button>
          </Stack>
        </form>
      )}
      <Anchor component={Link} to="/login" size="sm">{t("auth.login")}</Anchor>
    </Card>
  );
}

export function ResetPasswordPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const [msg, setMsg] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const recovery = params.get("type") === "recovery" || window.location.hash.includes("type=recovery");
  return (
    <Card title={t("auth.reset")}>
      {msg && <Alert>{msg}</Alert>}
      {recovery ? (
        <>
          <PasswordInput label={t("auth.newPassword")} value={password} onChange={(e) => setPassword(e.currentTarget.value)} />
          <Button onClick={async () => { const { error } = await supabase.auth.updateUser({ password }); setMsg(error?.message ?? "OK"); }}>{t("app.save")}</Button>
        </>
      ) : (
        <>
          <TextInput label={t("auth.email")} value={email} onChange={(e) => setEmail(e.currentTarget.value)} />
          <Button onClick={async () => {
            const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: `${window.location.origin}/reset-password?type=recovery` });
            setMsg(error?.message ?? t("auth.checkEmail"));
          }}>{t("auth.reset")}</Button>
        </>
      )}
    </Card>
  );
}

/** TOTP MFA: enroll if no factor, otherwise challenge → aal2 (required for the PILOTE console). */
export function MfaPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [factorId, setFactorId] = useState<string | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    void (async () => {
      const { data } = await supabase.auth.mfa.listFactors();
      const verified = data?.totp.find((f) => f.status === "verified");
      if (verified) return setFactorId(verified.id);
      const { data: enrolled, error: e } = await supabase.auth.mfa.enroll({ factorType: "totp" });
      if (e) return setError(e.message);
      setFactorId(enrolled.id);
      setQr(enrolled.totp.qr_code);
    })();
  }, []);
  const verify = async () => {
    if (!factorId) return;
    const { error: e } = await supabase.auth.mfa.challengeAndVerify({ factorId, code });
    if (e) return setError(e.message);
    await qc.invalidateQueries();
    navigate("/");
  };
  return (
    <Card title={qr ? t("auth.mfaEnroll") : t("auth.mfa")}>
      {error && <Alert color="red">{error}</Alert>}
      {qr && <Image src={qr} alt="TOTP QR" w={180} mx="auto" />}
      <Text size="sm">{t("auth.mfaCode")}</Text>
      <PinInput length={6} type="number" value={code} onChange={setCode} oneTimeCode />
      <Button onClick={verify} disabled={code.length !== 6}>{t("auth.verify")}</Button>
    </Card>
  );
}

const onboardingSchema = z.object({
  tenant_name: z.string().min(2).max(120),
  slug: z.string().regex(/^[a-z0-9-]{3,63}$/),
  full_name: z.string().max(120).optional(),
});

export function OnboardingPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const form = useForm<z.infer<typeof onboardingSchema>>({ resolver: zodResolver(onboardingSchema) });
  const m = useMutation({
    mutationFn: (body: z.infer<typeof onboardingSchema>) => api<{ tenant_id: string }>("/signup/demo", { method: "POST", body }),
    onSuccess: async (r) => { await qc.invalidateQueries({ queryKey: ["me"] }); navigate(`/t/${r.tenant_id}/dashboard`); },
  });
  return (
    <Card title={t("onboarding.title")}>
      <Text c="dimmed" size="sm">{t("onboarding.subtitle")}</Text>
      <form onSubmit={form.handleSubmit((v) => m.mutate(v))}>
        <Stack>
          <TextInput label={t("onboarding.tenantName")} {...form.register("tenant_name")} error={form.formState.errors.tenant_name?.message} />
          <TextInput label={t("onboarding.slug")} {...form.register("slug")} error={form.formState.errors.slug?.message} />
          <TextInput label={t("onboarding.fullName")} {...form.register("full_name")} />
          <Button type="submit" loading={m.isPending}>{t("onboarding.submit")}</Button>
        </Stack>
      </form>
    </Card>
  );
}

export function AcceptInvitationPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: () => api<{ tenant_id: string }>("/invitations/accept", { method: "POST", body: { token: params.get("token") } }),
    onSuccess: async (r) => { await qc.invalidateQueries({ queryKey: ["me"] }); navigate(`/t/${r.tenant_id}/dashboard`); },
  });
  return (
    <Card title="Invitation">
      {m.error && <Alert color="red">{m.error.message}</Alert>}
      <Button onClick={() => m.mutate()} loading={m.isPending}>OK</Button>
    </Card>
  );
}

export function HomeRedirect() {
  const { data, isLoading } = useMe();
  if (isLoading || !data) return <FullLoader />;
  const first = data.tenants[0];
  if (first) return <Navigate to={`/t/${first.id}/dashboard`} replace />;
  if (data.user.is_pilot) return <Navigate to="/pilot" replace />;
  return <Navigate to="/onboarding" replace />;
}
