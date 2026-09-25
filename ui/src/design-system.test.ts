import { describe, expect, it } from "vitest";
import shellHtml from "../src-tauri/shell-ui/index.html?raw";
import stylesheet from "./styles.css?raw";

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
  it("间距、字号、行高和字重不使用未命名的数值", () => {
    const declarations = [...stylesheet.matchAll(/^\s*([\w-]+)\s*:\s*([^;]+);/gm)];
    const violations = declarations
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
      .map(([, property, value]) => `${property}: ${value.trim()}`);

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
