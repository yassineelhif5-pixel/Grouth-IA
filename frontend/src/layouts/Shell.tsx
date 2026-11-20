import { AppShell, Avatar, Box, Burger, Group, Menu, NavLink, ScrollArea, Select, Stack, Text, UnstyledButton } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconChevronDown, IconLogout, IconSettings } from "@tabler/icons-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { Credit } from "@/components/Credit";
import { Preferences } from "@/components/Preferences";
import { useMe } from "@/hooks/useMe";
import { supabase } from "@/services/supabase";

export interface NavItem {
  to: string;
  label: string;
  icon?: ReactNode;
  group?: string;
}

function Brand() {
  return (
    <Group gap={10} wrap="nowrap">
      <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
        <defs>
          <linearGradient id="gi-mark" x1="0" y1="1" x2="1" y2="0">
            <stop offset="0" stopColor="#22c3b5" />
            <stop offset="1" stopColor="#8b7cf6" />
          </linearGradient>
        </defs>
        <rect x="1" y="1" width="26" height="26" rx="8" fill="none" stroke="url(#gi-mark)" strokeWidth="2" />
        <path d="M7 19 L12 13 L16 16 L21 8" fill="none" stroke="url(#gi-mark)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="21" cy="8" r="2.2" fill="#8b7cf6" />
      </svg>
      <Text fw={700} ff="heading" size="lg" style={{ letterSpacing: "-0.01em" }}>Growth IA</Text>
    </Group>
  );
}

export function Shell({ nav, header, banner }: { nav: NavItem[]; header?: ReactNode; banner?: ReactNode }) {
  const [opened, { toggle, close }] = useDisclosure();
  const { t } = useTranslation();
  const loc = useLocation();
  const { data } = useMe();
  const groups: { name: string; items: NavItem[] }[] = [];
  for (const n of nav) {
    const g = n.group ?? "";
    const found = groups.find((x) => x.name === g);
    if (found) found.items.push(n);
    else groups.push({ name: g, items: [n] });
  }
  const email = data?.user.email ?? "";
  return (
    <AppShell header={{ height: 60 }} navbar={{ width: 264, breakpoint: "sm", collapsed: { mobile: !opened } }} padding="xl">
      <AppShell.Header className="gi-glass" style={{ background: "color-mix(in srgb, var(--mantine-color-body) 82%, transparent)" }}>
        <Group h="100%" px="lg" justify="space-between" wrap="nowrap">
          <Group gap="md" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Menu" />
            <Brand />
            {header}
          </Group>
          <Group gap="sm" wrap="nowrap">
            <Preferences />
            <Menu position="bottom-end" width={240}>
              <Menu.Target>
                <UnstyledButton aria-label={email}>
                  <Group gap={8} wrap="nowrap">
                    <Avatar size={32} radius="xl" color="aurora">{email.slice(0, 2).toUpperCase()}</Avatar>
                    <Text size="sm" visibleFrom="md" maw={180} truncate>{email}</Text>
                    <IconChevronDown size={14} />
                  </Group>
                </UnstyledButton>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{email}</Menu.Label>
                {nav.find((n) => n.to.endsWith("/settings")) && (
                  <Menu.Item leftSection={<IconSettings size={16} />} component={Link} to={nav.find((n) => n.to.endsWith("/settings"))?.to ?? "/"}>
                    {t("nav.settings")}
                  </Menu.Item>
                )}
                <Menu.Item color="red" leftSection={<IconLogout size={16} />} onClick={() => void supabase.auth.signOut()}>{t("app.logout")}</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="sm" style={{ background: "color-mix(in srgb, var(--mantine-color-body) 92%, transparent)" }}>
        <AppShell.Section grow component={ScrollArea} type="hover">
          <Stack gap="md" py="xs">
            {groups.map((g) => (
              <Box key={g.name || "main"}>
                {g.name && <Text size="xs" c="dimmed" fw={600} px="sm" mb={4}>{g.name}</Text>}
                {g.items.map((n) => (
                  <NavLink key={n.to} component={Link} to={n.to} label={n.label} leftSection={n.icon} onClick={close}
                    active={loc.pathname === n.to || loc.pathname.startsWith(`${n.to}/`)} variant="light" style={{ borderRadius: 8 }} />
                ))}
              </Box>
            ))}
          </Stack>
        </AppShell.Section>
        <AppShell.Section pt="sm"><Credit /></AppShell.Section>
      </AppShell.Navbar>
      <AppShell.Main>
        <Box maw={1440} mx="auto">
          {banner}
          <Outlet />
        </Box>
      </AppShell.Main>
    </AppShell>
  );
}

export function TenantSwitcher({ current }: { current: string }) {
  const { data } = useMe();
  const navigate = useNavigate();
  if (!data || data.tenants.length < 2) return null;
  return (
    <Select size="xs" w={220} value={current} allowDeselect={false} aria-label="Tenant" visibleFrom="sm"
      data={data.tenants.map((x) => ({ value: x.id, label: x.name }))} onChange={(v) => v && navigate(`/t/${v}/dashboard`)} />
  );
}
