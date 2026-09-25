import { createTheme, type CSSVariablesResolver } from "@mantine/core";

const SPACING_SCALE = {
  xs: "0.25rem",
  sm: "0.5rem",
  md: "0.75rem",
  lg: "1rem",
  xl: "1.5rem",
} as const;

const EXTENDED_SPACING_SCALE = {
  xxl: "2rem",
  xxxl: "3rem",
} as const;

const FONT_SIZE_SCALE = {
  xs: "0.75rem",
  sm: "0.875rem",
  md: "1rem",
  lg: "1.125rem",
  xl: "1.375rem",
} as const;

const FONT_DISPLAY = "clamp(2rem, 4vw, 3.5rem)";

const FONT_WEIGHT = {
  regular: "400",
  medium: "500",
  semibold: "600",
  bold: "700",
  display: "800",
} as const;

const RADIUS_SCALE = {
  xs: "0.25rem",
  sm: "0.5rem",
  md: "0.875rem",
  lg: "1.25rem",
  xl: "1.5rem",
} as const;

const COMPONENT_METRICS = {
  controlHeight: "2.75rem",
  mobileNavHeight: "3.5rem",
  buttonPaddingInline: SPACING_SCALE.lg,
  tabPaddingInline: SPACING_SCALE.md,
  badgeHeight: "1.75rem",
  borderWidth: "0.0625rem",
  borderWidthStrong: "0.1875rem",
  focusOutlineWidth: "0.1875rem",
  focusOutlineOffset: "0.125rem",
  contentMax: "52rem",
} as const;

const LINE_HEIGHT = {
  display: "1.05",
  heading: "1.3",
  body: "1.65",
  reading: "1.75",
  caption: "1.4",
  control: "1.25",
} as const;

/** Sigma 画布按 community_id 稳定映射的分类色板；未分配节点单独使用中性灰。 */
export const GRAPH_COMMUNITY_COLORS = [
  "#2457d6",
  "#16724b",
  "#8a5b08",
  "#a43d3d",
  "#6b3fa0",
  "#0f7f8b",
  "#b0487f",
  "#4f6d1f",
  "#8c5a2b",
  "#2f4fa3",
  "#946b1d",
  "#5a6472",
] as const;
export const GRAPH_UNASSIGNED_COLOR = "#7b8798";

const primary: [string, string, string, string, string, string, string, string, string, string] = [
  "#edf2ff",
  "#dbe5ff",
  "#b8cbff",
  "#8eafff",
  "#5e8af2",
  "#376cdf",
  "#2457d6",
  "#173d9d",
  "#102f7a",
  "#0b225a",
];

export const theme = createTheme({
  primaryColor: "siku",
  colors: { siku: primary },
  defaultRadius: "sm",
  fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  fontFamilyMonospace: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSizes: FONT_SIZE_SCALE,
  spacing: SPACING_SCALE,
  radius: RADIUS_SCALE,
  headings: {
    fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    sizes: {
      h1: { fontSize: FONT_DISPLAY, lineHeight: LINE_HEIGHT.display, fontWeight: FONT_WEIGHT.display },
      h2: { fontSize: FONT_SIZE_SCALE.xl, lineHeight: LINE_HEIGHT.heading, fontWeight: FONT_WEIGHT.bold },
      h3: { fontSize: FONT_SIZE_SCALE.lg, lineHeight: LINE_HEIGHT.heading, fontWeight: FONT_WEIGHT.bold },
      h4: { fontSize: FONT_SIZE_SCALE.md, lineHeight: LINE_HEIGHT.caption, fontWeight: FONT_WEIGHT.bold },
      h5: { fontSize: FONT_SIZE_SCALE.sm, lineHeight: LINE_HEIGHT.caption, fontWeight: FONT_WEIGHT.bold },
      h6: { fontSize: FONT_SIZE_SCALE.xs, lineHeight: LINE_HEIGHT.caption, fontWeight: FONT_WEIGHT.bold },
    },
  },
});

export const cssVariablesResolver: CSSVariablesResolver = (currentTheme) => ({
  variables: {
    "--color-ink": "#182230",
    "--color-ink-soft": "#536174",
    "--color-ink-faint": "#626f81",
    "--color-canvas": "#f6f8fb",
    "--color-surface": "#ffffff",
    "--color-border": "#dce3ec",
    "--color-border-strong": "#c5cfdd",
    "--color-accent": currentTheme.colors.siku[6],
    "--color-accent-strong": currentTheme.colors.siku[7],
    "--color-accent-wash": currentTheme.colors.siku[0],
    "--color-success": "#16724b",
    "--color-warning": "#8a5b08",
    "--color-warning-wash": "#fff8e8",
    "--color-warning-border": "#ecd59d",
    "--color-danger": "#a43d3d",
    "--color-danger-wash": "#fff1f1",
    "--color-danger-border": "#efc2c2",
    "--font-display": FONT_DISPLAY,
    "--font-caption": FONT_SIZE_SCALE.xs,
    "--font-small": FONT_SIZE_SCALE.sm,
    "--font-body": FONT_SIZE_SCALE.md,
    "--font-subtitle": FONT_SIZE_SCALE.lg,
    "--font-heading": FONT_SIZE_SCALE.xl,
    "--weight-regular": FONT_WEIGHT.regular,
    "--weight-medium": FONT_WEIGHT.medium,
    "--weight-semibold": FONT_WEIGHT.semibold,
    "--weight-bold": FONT_WEIGHT.bold,
    "--weight-display": FONT_WEIGHT.display,
    "--line-display": LINE_HEIGHT.display,
    "--line-heading": LINE_HEIGHT.heading,
    "--line-body": LINE_HEIGHT.body,
    "--line-reading": LINE_HEIGHT.reading,
    "--line-caption": LINE_HEIGHT.caption,
    "--line-control": LINE_HEIGHT.control,
    "--space-1": SPACING_SCALE.xs,
    "--space-2": SPACING_SCALE.sm,
    "--space-3": SPACING_SCALE.md,
    "--space-4": SPACING_SCALE.lg,
    "--space-5": SPACING_SCALE.xl,
    "--space-6": EXTENDED_SPACING_SCALE.xxl,
    "--space-7": EXTENDED_SPACING_SCALE.xxxl,
    "--radius-sm": RADIUS_SCALE.sm,
    "--radius-md": RADIUS_SCALE.md,
    "--radius-lg": RADIUS_SCALE.lg,
    "--radius-pill": "999px",
    "--radius-circle": "50%",
    "--border-width": COMPONENT_METRICS.borderWidth,
    "--border-width-strong": COMPONENT_METRICS.borderWidthStrong,
    "--focus-outline-width": COMPONENT_METRICS.focusOutlineWidth,
    "--focus-outline-offset": COMPONENT_METRICS.focusOutlineOffset,
    "--shadow-card": "0 0.75rem 2rem rgb(24 34 48 / 0.06)",
    "--control-height": COMPONENT_METRICS.controlHeight,
    "--control-height-mobile-nav": COMPONENT_METRICS.mobileNavHeight,
    "--button-padding-inline": COMPONENT_METRICS.buttonPaddingInline,
    "--tab-padding-inline": COMPONENT_METRICS.tabPaddingInline,
    "--siku-service-badge-height": COMPONENT_METRICS.badgeHeight,
    "--content-max": COMPONENT_METRICS.contentMax,
  },
  light: {
    "--mantine-color-body": "#f6f8fb",
    "--mantine-color-text": "#182230",
  },
  dark: {},
});
