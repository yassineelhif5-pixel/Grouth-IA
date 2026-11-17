import { AppShell, Burger, Button, Group, NavLink, Select, Text } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { Preferences } from "@/components/Preferences";
import { useMe } from "@/hooks/useMe";
import { supabase } from "@/services/supabase";

export interface NavItem {
  to: string;
  label: string;
  icon?: ReactNode;
}

export function Shell({ nav, header }: { nav: NavItem[]; header?: ReactNode }) {
  const [opened, { toggle }] = useDisclosure();
  const { t } = useTranslation();
  const loc = useLocation();
  const { data } = useMe();
  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 240, breakpoint: "sm", collapsed: { mobile: !opened } }} padding="lg">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group>
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Text fw={700}>{t("app.name")}</Text>
            {header}
          </Group>
          <Group>
            <Preferences />
            <Text size="sm" c="dimmed" visibleFrom="sm">{data?.user.email}</Text>
            <Button size="xs" variant="default" onClick={() => void supabase.auth.signOut()}>{t("app.logout")}</Button>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        {nav.map((n) => (
          <NavLink key={n.to} component={Link} to={n.to} label={n.label} leftSection={n.icon} active={loc.pathname === n.to || loc.pathname.startsWith(`${n.to}/`)} />
        ))}
      </AppShell.Navbar>
      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  );
}

export function TenantSwitcher({ current }: { current: string }) {
  const { data } = useMe();
  const navigate = useNavigate();
  if (!data || data.tenants.length < 2) return null;
  return (
    <Select size="xs" w={200} value={current} allowDeselect={false}
      data={data.tenants.map((x) => ({ value: x.id, label: x.name }))} onChange={(v) => v && navigate(`/t/${v}`)} />
  );
}
