import { Anchor, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";

/** Mention de l'éditeur du SaaS, affichée sur toutes les pages. */
export function Credit() {
  const { t } = useTranslation();
  return (
    <Text size="xs" c="dimmed" ta="center">
      {t("app.developedBy")}{" "}
      <Anchor href="https://zirconai.fr" target="_blank" rel="noopener noreferrer" size="xs">zirconai.fr</Anchor>
    </Text>
  );
}
