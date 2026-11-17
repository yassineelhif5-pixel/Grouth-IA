import { Badge } from "@mantine/core";

const COLORS: Record<string, string> = {
  healthy: "green", success: "green", succeeded: "green", active: "green", enabled: "green", passed: "green",
  degraded: "yellow", trialing: "blue", pending: "gray", running: "blue", queued: "gray", retrying: "orange",
  down: "red", failed: "red", failure: "red", denied: "red", suspended: "red", expired: "red", dead_letter: "red",
  not_configured: "gray", unknown: "gray", checking: "blue", disabled: "gray",
};

export function StatusBadge({ value }: { value: string | null | undefined }) {
  const v = value ?? "unknown";
  return (
    <Badge color={COLORS[v] ?? "gray"} variant="light">
      {v.replace(/_/g, " ")}
    </Badge>
  );
}
