import { describe, expect, it } from "vitest";
import type { MantineColorsTuple, MantineTheme } from "@mantine/core";
import shellHtml from "../src-tauri/shell-ui/index.html?raw";
import stylesheet from "./styles.css?raw";
import { cssVariablesResolver, theme } from "./theme";

const governedProperties = new Set([
  "margin",
  "margin-block",
  "margin-inline",
  "margin-top",
  "margin-right",
  "margin-bottom",
  "margin-left",
  "padding",
  "padding-block",
  "padding-inline",
  "padding-top",
  "padding-right",
  "padding-bottom",
  "padding-left",
  "gap",
  "row-gap",
  "column-gap",
  "font-size",
  "line-height",
  "font-weight",
]);
const spacingProperties = new Set([
  "margin",
  "margin-block",
  "margin-inline",
  "margin-top",
  "margin-right",
  "margin-bottom",
  "margin-left",
  "padding",
  "padding-block",
  "padding-inline",
  "padding-top",
  "padding-right",
  "padding-bottom",
  "padding-left",
  "gap",
  "row-gap",
  "column-gap",
]);
const borderProperties = new Set(["border", "border-top", "border-right", "border-bottom", "border-left"]);

function ungovernedBorderWidths(css: string): string[] {
  return [...css.matchAll(/^\s*([\w-]+)\s*:\s*([^;]+);/gm)]
    .filter(([, property, value]) => {
      if (!borderProperties.has(property)) {
        return false;
      }
      const normalizedValue = value.trim();
      return !/var\(--border-width(?:-strong)?\)/.test(normalizedValue) && !/^(?:0|none)$/.test(normalizedValue);
    })
    .map(([, property, value]) => `${property}: ${value.trim()}`);
}

function ungovernedCornerRadii(css: string): string[] {
  return [...css.matchAll(/^\s*([\w-]+)\s*:\s*([^;]+);/gm)]
    .filter(([, property, value]) => {
      if (property !== "border-radius") {
        return false;
      }
      const normalizedValue = value.trim();
      return !/var\(--radius-[\w-]+\)/.test(normalizedValue) && !/^(?:0|none)$/.test(normalizedValue);
    })
    .map(([, property, value]) => `${property}: ${value.trim()}`);
}

describe("全局设计 token", () => {
  it("应用与静态启动页的间距、字号、行高和字重不使用未命名的数值", () => {
    const violations = [stylesheet, shellHtml].flatMap((source) =>
      [...source.matchAll(/^\s*([\w-]+)\s*:\s*([^;]+);/gm)]
        .filter(([, property, value]) => {
          if (!governedProperties.has(property)) {
            return false;
          }
          const normalizedValue = value.trim();
          if (spacingProperties.has(property)) {
            const usesSpacingToken = /var\(--(?:space-|control-height|button-padding-inline|tab-padding-inline)/.test(
              normalizedValue,
            );
            const resetValue = /^(?:0|auto)(?:\s+(?:0|auto))*$/.test(normalizedValue);
            return !usesSpacingToken && !resetValue;
          }
          if (property === "font-size") {
            return !normalizedValue.startsWith("var(--font-") && !["inherit", "initial"].includes(normalizedValue);
          }
          if (property === "line-height") {
            return !normalizedValue.startsWith("var(--line-") && !["inherit", "normal"].includes(normalizedValue);
          }
          if (property === "font-weight") {
            return !normalizedValue.startsWith("var(--weight-") && !["inherit", "normal"].includes(normalizedValue);
          }
          return false;
        })
        .map(([property, value]) => `${property}: ${value.trim()}`),
    );

    expect(violations).toEqual([]);
  });

  it("应用与静态启动页的边框宽度都使用已命名 token", () => {
    expect(ungovernedBorderWidths(stylesheet)).toEqual([]);
    expect(ungovernedBorderWidths(shellHtml)).toEqual([]);
  });

  it("应用与静态启动页的圆角都使用已命名 token", () => {
    expect(ungovernedCornerRadii(stylesheet)).toEqual([]);
    expect(ungovernedCornerRadii(shellHtml)).toEqual([]);
  });
});

/** WCAG 相对亮度（sRGB 通道线性化后按人眼敏感度加权）。 */
function relativeLuminance(hex: string): number {
  const channels = [0, 2, 4].map((start) => {
    const channel = Number.parseInt(hex.replace("#", "").slice(start, start + 2), 16) / 255;
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrastRatio(foreground: string, background: string): number {
  const lighter = Math.max(relativeLuminance(foreground), relativeLuminance(background));
  const darker = Math.min(relativeLuminance(foreground), relativeLuminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

describe("语义色与 Mantine 色板同源", () => {
  // createTheme 返回类型是 PartialObjectDeep（便于做 override），运行时是完整主题
  const variables = cssVariablesResolver(theme as MantineTheme).variables;
  // createTheme 注入的 colors 经索引签名访问被推为可空，测试目标恰是这三个 ramp 必须存在
  const { green, yellow, red } = theme.colors as Record<"green" | "yellow" | "red", MantineColorsTuple>;

  it("语义色 token 全部取自被覆盖的 Mantine 色阶，不允许另写裸值", () => {
    expect(variables["--color-success"]).toBe(green[6]);
    expect(variables["--color-warning"]).toBe(yellow[6]);
    expect(variables["--color-warning-wash"]).toBe(yellow[1]);
    expect(variables["--color-warning-border"]).toBe(yellow[2]);
    expect(variables["--color-danger"]).toBe(red[6]);
    expect(variables["--color-danger-strong"]).toBe(red[7]);
    expect(variables["--color-danger-wash"]).toBe(red[1]);
    expect(variables["--color-danger-border"]).toBe(red[2]);
  });

  it("覆盖的三个色阶在浅底上的文字对比度 ≥4.5:1（Alert/Badge light 文字与状态卡正文）", () => {
    for (const ramp of [green, yellow, red]) {
      // 阶位口径见 theme.ts：1=浅底、6=核心（状态卡正文）、9=light 变体文字
      expect(contrastRatio(ramp[9], ramp[1])).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(ramp[6], ramp[1])).toBeGreaterThanOrEqual(4.5);
    }
  });
});
