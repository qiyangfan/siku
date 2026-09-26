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

/**
 * 覆盖 Mantine 默认 green/yellow/red 色阶：Alert/Badge 的 color 属性与下方
 * CSS 语义 token 从此同源，杜绝「Mantine 默认鲜亮板」与「siku muted 语义色」
 * 两套体系并存。阶位口径：1=浅底(wash)、2=描边、6=核心、7=加深、9=浅底上的
 * 文字；1↔9 与 1↔6 的对比度由 design-system.test.ts 守卫（≥4.5:1）。
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

/** 画布边线色：ink 的透明派生（canvas 绘制读不到 CSS 变量，只能常量化）。 */
export const GRAPH_EDGE_COLOR = rgba(INK, 0.18);

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
    // 用 siku 语义 ramp 顶替默认色板：组件写 color="green|yellow|red" 即得语义色，
    // 不存在「顺手写默认色名却拿到 Mantine 原色」的回退路径。
    // gray 有意豁免：中性系无语义角色，且 Mantine 默认 gray 同时驱动次级按钮、
    // 输入框描边等组件 chrome，覆盖会波及全部默认件外观
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
  variables: {
    "--color-ink": INK,
    // 辅助字对比度达标口径（≥4.5:1，UI 闸门硬底线）：曾在浅灰画布上仅 3.1–3.9:1
    "--color-ink-soft": "#47525f",
    "--color-ink-faint": "#545f6e",
    "--color-canvas": CANVAS,
    "--color-surface": "#ffffff",
    "--color-border": "#dce3ec",
    "--color-border-strong": "#c5cfdd",
    "--color-accent": currentTheme.colors.siku[6],
    "--color-accent-strong": currentTheme.colors.siku[7],
    "--color-accent-wash": currentTheme.colors.siku[0],
    // 语义色一律取自上方被覆盖的 Mantine 色阶（阶位口径见 ramp 注释），
    // 与组件 color="green|yellow|red" 天然同色；design-system.test.ts 守卫同源性
    "--color-success": currentTheme.colors.green[6],
    "--color-warning": currentTheme.colors.yellow[6],
    "--color-warning-wash": currentTheme.colors.yellow[1],
    "--color-warning-border": currentTheme.colors.yellow[2],
    "--color-danger": currentTheme.colors.red[6],
    "--color-danger-strong": currentTheme.colors.red[7],
    "--color-danger-wash": currentTheme.colors.red[1],
    "--color-danger-border": currentTheme.colors.red[2],
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
    "--mantine-color-body": CANVAS,
    "--mantine-color-text": INK,
  },
  dark: {},
});
