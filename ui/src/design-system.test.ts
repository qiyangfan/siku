import { describe, expect, it } from "vitest";
import { ColorSchemeScript } from "@mantine/core";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { MantineColorsTuple, MantineTheme } from "@mantine/core";
import appHtml from "../index.html?raw";
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

describe("首帧主题初始化脚本与库同源", () => {
  // 防漂移：两处 HTML 入口内联的脚本必须逐字节等于 @mantine/core 的
  // ColorSchemeScript（defaultColorScheme="auto"）产物，不得手写分叉
  const canonicalInitScript = renderToStaticMarkup(
    createElement(ColorSchemeScript, { defaultColorScheme: "auto" }),
  )
    .replace(/^<script[^>]*>/, "")
    .replace(/<\/script>$/, "")
    .trim();

  it("应用与壳静态启动页内联的初始化脚本与 ColorSchemeScript 产物一致", () => {
    expect(appHtml).toContain(canonicalInitScript);
    expect(shellHtml).toContain(canonicalInitScript);
  });

  it("html 元素带静态亮色兜底属性（脚本被禁用时不至无主题变量）", () => {
    expect(appHtml).toMatch(/<html[^>]*data-mantine-color-scheme="light"/);
    expect(shellHtml).toMatch(/<html[^>]*data-mantine-color-scheme="light"/);
  });
});

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

describe("主题两态取值分流", () => {
  const resolved = cssVariablesResolver(theme as MantineTheme);

  it("方案相关 token（色彩/投影）不留在两态共用 variables", () => {
    const schemeToken = /--(?:color-|shadow-)/;
    expect(Object.keys(resolved.variables).filter((name) => schemeToken.test(name))).toEqual([]);
  });

  it("主题块只承载方案相关 token，度量与排印刻度不得进入任一态", () => {
    for (const schemeVariables of [resolved.light, resolved.dark]) {
      const foreign = Object.keys(schemeVariables).filter(
        (name) => !name.startsWith("--color-") && !name.startsWith("--shadow-") && !name.startsWith("--mantine-"),
      );
      expect(foreign).toEqual([]);
    }
  });
});

describe("暗色取值对比度守卫", () => {
  // 守卫按 token 名逐条断言，值本身经 Mantine CSSVariables 索引访问
  const dark = cssVariablesResolver(theme as MantineTheme).dark as Record<string, string>;
  const { red } = theme.colors as Record<"red", MantineColorsTuple>;
  const darkCanvas = dark["--color-canvas"];
  const darkSurface = dark["--color-surface"];

  it("正文/辅助字/强调与语义核心色对暗 canvas 与暗 surface 均 ≥4.5:1", () => {
    for (const token of [
      "--color-ink",
      "--color-ink-soft",
      "--color-ink-faint",
      "--color-accent",
      "--color-success",
      "--color-warning",
      "--color-danger",
    ]) {
      expect(contrastRatio(dark[token], darkCanvas)).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(dark[token], darkSurface)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("暗 wash 上的文字 ≥4.5:1；红族钉 3 阶，4 阶不达标的差异用断言钉住", () => {
    // 红色浅底上的文字使用第 3 阶；第 4 阶对比度只有 3.84:1。
    expect(dark["--color-danger"]).toBe(red[3]);
    expect(dark["--color-danger-wash"]).toBe(red[9]);
    expect(contrastRatio(dark["--color-danger"], dark["--color-danger-wash"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(red[4], dark["--color-danger-wash"])).toBeLessThan(4.5);

    expect(contrastRatio(dark["--color-warning"], dark["--color-warning-wash"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(dark["--color-accent"], dark["--color-accent-wash"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(dark["--color-accent-strong"], dark["--color-accent-wash"])).toBeGreaterThanOrEqual(4.5);
  });

  it("暗色边线保持 hairline 分隔语义（低于文字阈值，刻意为之）", () => {
    expect(contrastRatio(dark["--color-border"], darkCanvas)).toBeLessThan(4.5);
    expect(contrastRatio(dark["--color-border-strong"], darkCanvas)).toBeLessThan(4.5);
  });
});

describe("语义色与 Mantine 色板同源", () => {
  // createTheme 返回类型是 PartialObjectDeep（便于做 override），运行时是完整主题
  const resolved = cssVariablesResolver(theme as MantineTheme);
  // createTheme 注入的 colors 经索引签名访问被推为可空，测试目标恰是这三个 ramp 必须存在
  const { green, yellow, red } = theme.colors as Record<"green" | "yellow" | "red", MantineColorsTuple>;
  const { siku } = theme.colors as Record<"siku", MantineColorsTuple>;

  it("亮色语义 token 全部取自被覆盖的 Mantine 色阶，不允许另写裸值", () => {
    const light = resolved.light;
    expect(light["--color-accent"]).toBe(siku[6]);
    expect(light["--color-accent-strong"]).toBe(siku[7]);
    expect(light["--color-accent-wash"]).toBe(siku[0]);
    expect(light["--color-success"]).toBe(green[6]);
    expect(light["--color-warning"]).toBe(yellow[6]);
    expect(light["--color-warning-wash"]).toBe(yellow[1]);
    expect(light["--color-warning-border"]).toBe(yellow[2]);
    expect(light["--color-danger"]).toBe(red[6]);
    expect(light["--color-danger-strong"]).toBe(red[7]);
    expect(light["--color-danger-wash"]).toBe(red[1]);
    expect(light["--color-danger-border"]).toBe(red[2]);
  });

  it("暗色语义 token 同样取自 Mantine 色阶（D3 阶位映射），不另写裸值", () => {
    const dark = resolved.dark;
    expect(dark["--color-accent"]).toBe(siku[4]);
    expect(dark["--color-accent-strong"]).toBe(siku[3]);
    expect(dark["--color-accent-wash"]).toBe(siku[9]);
    expect(dark["--color-success"]).toBe(green[4]);
    expect(dark["--color-warning"]).toBe(yellow[3]);
    expect(dark["--color-warning-wash"]).toBe(yellow[9]);
    expect(dark["--color-warning-border"]).toBe(yellow[5]);
    expect(dark["--color-danger"]).toBe(red[3]);
    expect(dark["--color-danger-strong"]).toBe(red[4]);
    expect(dark["--color-danger-wash"]).toBe(red[9]);
    expect(dark["--color-danger-border"]).toBe(red[5]);
  });

  it("覆盖的三个色阶在浅底上的文字对比度 ≥4.5:1（Alert/Badge light 文字与状态卡正文）", () => {
    for (const ramp of [green, yellow, red]) {
      // 阶位口径见 theme.ts：1=浅底、6=核心（状态卡正文）、9=light 变体文字
      expect(contrastRatio(ramp[9], ramp[1])).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(ramp[6], ramp[1])).toBeGreaterThanOrEqual(4.5);
    }
  });
});
