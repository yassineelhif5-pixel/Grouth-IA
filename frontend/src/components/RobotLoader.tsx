import { Stack, Text } from "@mantine/core";
import { useEffect, useState } from "react";

import "./robot-loader.css";

/**
 * Loading indicator: a 3D robot "thinking", with a percentage.
 * - progress given  → real progress (audit, scan…), shown as is.
 * - progress absent → page loading: the percentage advances towards 95 % while the data loads
 *   (no real percentage exists for an HTTP request; the component disappears as soon as the page is ready).
 */
export function RobotLoader({ progress, label, size = "md", minHeight }: { progress?: number; label?: string; size?: "sm" | "md" | "lg"; minHeight?: number | string }) {
  const [auto, setAuto] = useState(4);
  useEffect(() => {
    if (progress !== undefined) return;
    const id = window.setInterval(() => setAuto((p) => (p >= 95 ? p : p + Math.max(0.4, (95 - p) * 0.06))), 120);
    return () => window.clearInterval(id);
  }, [progress]);
  const pct = Math.round(Math.max(0, Math.min(100, progress ?? auto)));
  const scale = size === "sm" ? 0.55 : size === "lg" ? 1.25 : 0.9;
  return (
    <Stack align="center" justify="center" gap={size === "sm" ? 4 : "sm"} mih={minHeight ?? (size === "sm" ? 140 : 320)} role="status" aria-live="polite" aria-label={`${label ?? "Chargement"} ${pct} %`}>
      <div className="gi-robot-stage" style={{ ["--gi-scale" as string]: scale, ["--gi-pct" as string]: `${pct * 3.6}deg` }}>
        <div className="gi-orbit"><span className="gi-orbit-dot" /></div>
        <div className="gi-thoughts"><span /><span /><span /></div>
        <div className="gi-robot">
          <div className="gi-antenna"><span className="gi-antenna-bulb" /></div>
          <div className="gi-head">
            <span className="gi-ear gi-ear-l" />
            <span className="gi-ear gi-ear-r" />
            <div className="gi-visor">
              <span className="gi-eye" />
              <span className="gi-eye" />
              <span className="gi-scanline" />
            </div>
          </div>
          <div className="gi-neck" />
          <div className="gi-body">
            <div className="gi-core"><span className="gi-num">{pct}</span></div>
            <span className="gi-arm gi-arm-l" />
            <span className="gi-arm gi-arm-r" />
          </div>
        </div>
        <div className="gi-shadow" />
      </div>
      <Text className="gi-num" fw={600} ff="heading" fz={size === "sm" ? 18 : 28} lh={1}>{pct} %</Text>
      {label !== "" && <Text size={size === "sm" ? "xs" : "sm"} c="dimmed" ta="center" maw={420}>{label ?? "L'IA prépare votre page…"}</Text>}
    </Stack>
  );
}
