import { createTheme, type MantineColorsTuple } from "@mantine/core";

/** Growth IA design tokens.
 *  - signal (teal): data actually observed (crawl, HTTP checks, API tests)
 *  - aurora (violet): anything produced by AI (summaries, drafts, suggestions)
 *  - night: the deep-navy surfaces of the dark theme, easier on the eyes than pure black */
const signal: MantineColorsTuple = ["#e3fbf8", "#c3f3ee", "#93e8df", "#5fdccf", "#36d0c1", "#22c3b5", "#16a297", "#0f8178", "#0b625b", "#06433f"];
const aurora: MantineColorsTuple = ["#f1eeff", "#e1dbff", "#c4b8ff", "#a897fb", "#9585f8", "#8b7cf6", "#7262de", "#5a4bb8", "#443890", "#2f2669"];
const night: MantineColorsTuple = ["#e7ecf5", "#c3cbdb", "#9aa6bd", "#6f7d98", "#4a5874", "#2e3b55", "#1f2c45", "#18243a", "#121d30", "#0d1626"];

export const theme = createTheme({
  primaryColor: "signal",
  primaryShade: { light: 6, dark: 5 },
  colors: { signal, aurora, dark: night },
  fontFamily: "'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', sans-serif",
  fontFamilyMonospace: "'IBM Plex Mono', ui-monospace, monospace",
  headings: {
    fontFamily: "Sora, 'IBM Plex Sans', system-ui, sans-serif",
    fontWeight: "600",
    sizes: { h1: { fontSize: "2rem", lineHeight: "1.2" }, h2: { fontSize: "1.5rem", lineHeight: "1.25" }, h3: { fontSize: "1.2rem", lineHeight: "1.3" } },
  },
  defaultRadius: "md",
  radius: { xs: "4px", sm: "6px", md: "10px", lg: "14px", xl: "20px" },
  cursorType: "pointer",
  components: {
    Card: { defaultProps: { withBorder: true, radius: "lg", padding: "lg" } },
    Paper: { defaultProps: { radius: "lg" } },
    Button: { defaultProps: { radius: "md" } },
    Badge: { defaultProps: { radius: "sm", variant: "light" } },
    Table: { defaultProps: { verticalSpacing: "sm", highlightOnHover: true } },
    Modal: { defaultProps: { radius: "lg", centered: true, overlayProps: { backgroundOpacity: 0.55, blur: 3 } } },
    Tooltip: { defaultProps: { withArrow: true } },
  },
});
