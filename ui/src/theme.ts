import {
  createTheme,
  rgba,
  type CSSVariablesResolver,
  type MantineColorsTuple,
} from "@mantine/core";

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

// 语义锚点色：成功/警告/危险三族的核心色，与图谱社区色板共用同一组值。
// ink 与 canvas 同时被 Mantine 的 body/text 覆盖引用，必须单点定义。
const SEMANTIC_GREEN = "#16724b";
const SEMANTIC_AMBER = "#8a5b08";
const SEMANTIC_RED = "#a43d3d";
const INK = "#182230";
const CANVAS = "#f6f8fb";

// 暗色值沿用亮色的色相，并按对比度调整明度。
const DARK_INK = "#e6ecf3";
const DARK_CANVAS = "#10161d";
const DARK_SURFACE = "#182230";
const DARK_INK_SOFT = "#a7b3c2";
const DARK_INK_FAINT = "#8b98a8";
const DARK_BORDER = "#2a3644";
const DARK_BORDER_STRONG = "#3a4a5c";

/**
 * 覆盖 Mantine 默认的 green/yellow/red 色阶，使组件颜色与 CSS 语义 token 同源。
 * 阶位：1=浅底、2=描边、6=核心、7=加深、9=浅底文字；浅底与文字对比度至少为 4.5:1。
 */
const SUCCESS_RAMP: MantineColorsTuple = [
  "#eef7f2",
  "#e3f2ea",
  "#bfe0cf",
  "#8fcbaf",
  "#5cb48d",
  "#339a70",
  SEMANTIC_GREEN,
  "#115e3e",
  "#0d4a31",
  "#093825",
];
const WARNING_RAMP: MantineColorsTuple = [
  "#fffaef",
  "#fff8e8",
  "#ecd59d",
  "#e0bc6c",
  "#cfa344",
  "#ad8420",
  SEMANTIC_AMBER,
  "#6f4807",
  "#593906",
  "#482d05",
];
const DANGER_RAMP: MantineColorsTuple = [
  "#fff8f7",
  "#fff1f1",
  "#efc2c2",
  "#e29a99",
  "#d07c7b",
  "#bd5d5c",
  SEMANTIC_RED,
  "#8f3232",
  "#78292a",
  "#632223",
];

/** Sigma 画布按 community_id 稳定映射的分类色板；未分配节点单独使用中性灰。 */
export const GRAPH_COMMUNITY_COLORS = [
  "#2457d6",
  SEMANTIC_GREEN,
  SEMANTIC_AMBER,
  SEMANTIC_RED,
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

/**
 * 画布绘制无法读取 CSS 变量，这里集中提供边线与标签色（亮暗两套）。
 */
export function graphCanvasThemeColors(colorScheme: "light" | "dark"): { edge: string; label: string } {
  return colorScheme === "dark"
    ? { edge: rgba(DARK_INK, 0.18), label: DARK_INK }
    : { edge: rgba(INK, 0.18), label: INK };
}

const primary: MantineColorsTuple = [
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
  colors: {
    siku: primary,
    // 用 siku 语义色阶替换 Mantine 默认 green/yellow/red；gray 保留默认以避免影响通用外观。
    green: SUCCESS_RAMP,
    yellow: WARNING_RAMP,
    red: DANGER_RAMP,
  },
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
  // 共享变量只放度量和排印；颜色与投影分别配置于 light 和 dark。
  variables: {
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
    "--control-height": COMPONENT_METRICS.controlHeight,
    "--control-height-mobile-nav": COMPONENT_METRICS.mobileNavHeight,
    "--button-padding-inline": COMPONENT_METRICS.buttonPaddingInline,
    "--tab-padding-inline": COMPONENT_METRICS.tabPaddingInline,
    "--siku-service-badge-height": COMPONENT_METRICS.badgeHeight,
    "--content-max": COMPONENT_METRICS.contentMax,
  },
  light: {
    "--color-ink": INK,
    // 辅助文字与画布的对比度至少为 4.5:1。
    "--color-ink-soft": "#47525f",
    "--color-ink-faint": "#545f6e",
    "--color-canvas": CANVAS,
    "--color-surface": "#ffffff",
    "--color-border": "#dce3ec",
    "--color-border-strong": "#c5cfdd",
    "--color-accent": currentTheme.colors.siku[6],
    "--color-accent-strong": currentTheme.colors.siku[7],
    "--color-accent-wash": currentTheme.colors.siku[0],
    // 语义色取自上方覆盖的 Mantine 色阶，与组件 color 属性保持一致。
    "--color-success": currentTheme.colors.green[6],
    "--color-warning": currentTheme.colors.yellow[6],
    "--color-warning-wash": currentTheme.colors.yellow[1],
    "--color-warning-border": currentTheme.colors.yellow[2],
    "--color-danger": currentTheme.colors.red[6],
    "--color-danger-strong": currentTheme.colors.red[7],
    "--color-danger-wash": currentTheme.colors.red[1],
    "--color-danger-border": currentTheme.colors.red[2],
    "--shadow-card": "0 0.75rem 2rem rgb(24 34 48 / 0.06)",
    "--mantine-color-body": CANVAS,
    "--mantine-color-text": INK,
  },
  // 暗色语义色按各自色阶选择，确保文字与浅底对比度至少为 4.5:1。
  // 红色使用第 3 阶（第 4 阶对比度仅 3.84:1）；accent 与浅底约为 4.6:1。
  dark: {
    "--color-ink": DARK_INK,
    "--color-ink-soft": DARK_INK_SOFT,
    "--color-ink-faint": DARK_INK_FAINT,
    "--color-canvas": DARK_CANVAS,
    "--color-surface": DARK_SURFACE,
    "--color-border": DARK_BORDER,
    "--color-border-strong": DARK_BORDER_STRONG,
    "--color-accent": currentTheme.colors.siku[4],
    "--color-accent-strong": currentTheme.colors.siku[3],
    "--color-accent-wash": currentTheme.colors.siku[9],
    "--color-success": currentTheme.colors.green[4],
    "--color-warning": currentTheme.colors.yellow[3],
    "--color-warning-wash": currentTheme.colors.yellow[9],
    "--color-warning-border": currentTheme.colors.yellow[5],
    "--color-danger": currentTheme.colors.red[3],
    "--color-danger-strong": currentTheme.colors.red[4],
    "--color-danger-wash": currentTheme.colors.red[9],
    "--color-danger-border": currentTheme.colors.red[5],
    // 暗色投影加深：亮色 ink 投影在暗底不可见
    "--shadow-card": "0 0.75rem 2rem rgb(0 0 0 / 0.35)",
    "--mantine-color-body": DARK_CANVAS,
    "--mantine-color-text": DARK_INK,
  },
});
