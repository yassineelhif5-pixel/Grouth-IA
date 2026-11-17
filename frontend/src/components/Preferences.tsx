import { ActionIcon, Group, SegmentedControl, useMantineColorScheme } from "@mantine/core";
import { IconMoon, IconSun } from "@tabler/icons-react";
import { useTranslation } from "react-i18next";

export function Preferences() {
  const { i18n } = useTranslation();
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  return (
    <Group gap="xs">
      <SegmentedControl size="xs" value={i18n.language} onChange={(v) => void i18n.changeLanguage(v)} data={[{ value: "fr", label: "FR" }, { value: "en", label: "EN" }]} />
      <ActionIcon variant="default" aria-label="theme" onClick={() => setColorScheme(colorScheme === "dark" ? "light" : "dark")}>
        {colorScheme === "dark" ? <IconSun size={16} /> : <IconMoon size={16} />}
      </ActionIcon>
    </Group>
  );
}
