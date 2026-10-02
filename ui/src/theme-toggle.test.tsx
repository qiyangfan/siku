import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ThemeToggle } from "./ThemeToggle";
import { renderAuto, renderInColorScheme } from "./test-utils";

const COLOR_SCHEME_KEY = "mantine-color-scheme-value";

type SystemPreference = "light" | "dark";

// test-setup 的 matchMedia 桩固定 matches:false（亮色）；主题接线测试需要
// 可切换的系统偏好，这里按用例覆写（属性以 writable:true 定义，可直接赋值）
function mockSystemPreference(preference: SystemPreference) {
  window.matchMedia = ((media: string): MediaQueryList => {
    const matches = preference === "dark" && media === "(prefers-color-scheme: dark)";
    return {
      matches,
      media,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    };
  }) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-mantine-color-scheme");
  mockSystemPreference("light");
});

afterEach(() => {
  cleanup();
});

describe("主题切换入口", () => {
  it("初始跟随系统：暗色偏好下首帧即暗态，不写入手动值", () => {
    mockSystemPreference("dark");
    renderAuto(<ThemeToggle />);

    expect(document.documentElement.getAttribute("data-mantine-color-scheme")).toBe("dark");
    expect(screen.getByRole("button", { name: "切换为亮色" })).toBeInTheDocument();
    expect(window.localStorage.getItem(COLOR_SCHEME_KEY)).toBeNull();
  });

  it("亮色系统下入口明示目标态为暗色", () => {
    renderAuto(<ThemeToggle />);

    expect(document.documentElement.getAttribute("data-mantine-color-scheme")).toBe("light");
    expect(screen.getByRole("button", { name: "切换为暗色" })).toBeInTheDocument();
  });

  it("点击后写入手动值并跨渲染持久化，入口标签随目标态反转", async () => {
    const user = userEvent.setup();
    mockSystemPreference("dark");
    const { unmount } = renderAuto(<ThemeToggle />);

    await user.click(screen.getByRole("button", { name: "切换为亮色" }));

    expect(window.localStorage.getItem(COLOR_SCHEME_KEY)).toBe("light");
    expect(document.documentElement.getAttribute("data-mantine-color-scheme")).toBe("light");
    expect(screen.getByRole("button", { name: "切换为暗色" })).toBeInTheDocument();

    unmount();
    // 手动值优先：重开（新 provider 实例）后仍是手动选择的亮色
    renderAuto(<ThemeToggle />);
    expect(document.documentElement.getAttribute("data-mantine-color-scheme")).toBe("light");
    expect(screen.getByRole("button", { name: "切换为暗色" })).toBeInTheDocument();
  });

  it("强制暗色包裹下入口明示目标态为亮色（两态渲染确定性基线）", () => {
    renderInColorScheme(<ThemeToggle />, "dark");

    expect(document.documentElement.getAttribute("data-mantine-color-scheme")).toBe("dark");
    expect(screen.getByRole("button", { name: "切换为亮色" })).toBeInTheDocument();
  });
});
