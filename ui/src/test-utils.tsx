import { MantineProvider } from "@mantine/core";
import {
  render as testingLibraryRender,
  type RenderOptions,
} from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { cssVariablesResolver, theme } from "./theme";

type ColorScheme = "light" | "dark";

function withProvider(
  ui: ReactElement,
  providerProps:
    { forceColorScheme: ColorScheme } | { defaultColorScheme: "auto" },
  options?: RenderOptions,
) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MantineProvider
        theme={theme}
        cssVariablesResolver={cssVariablesResolver}
        {...providerProps}
      >
        {children}
      </MantineProvider>
    );
  }
  return testingLibraryRender(<Wrapper>{ui}</Wrapper>, options);
}

/** 默认亮色固定：绝大多数组件测试需要确定性基线。 */
export function render(ui: ReactElement, options?: RenderOptions) {
  return withProvider(ui, { forceColorScheme: "light" }, options);
}

/** 暗色包裹入口：组件两态渲染测试用。 */
export function renderInColorScheme(
  ui: ReactElement,
  colorScheme: ColorScheme,
  options?: RenderOptions,
) {
  return withProvider(ui, { forceColorScheme: colorScheme }, options);
}

/** 跟随系统入口（auto，不固定）：主题接线与切换入口测试用。 */
export function renderAuto(ui: ReactElement, options?: RenderOptions) {
  return withProvider(ui, { defaultColorScheme: "auto" }, options);
}

/** 取 fetch 调用参数的 URL 文本；测试注入的输入只有这三种合法形态。 */
export function requestUrl(input: unknown): string {
  if (typeof input === "string") {
    return input;
  }
  if (input instanceof URL) {
    return input.href;
  }
  if (input instanceof Request) {
    return input.url;
  }
  return "";
}

/** 取 fetch 调用参数的请求体文本；测试只发送字符串体。 */
export function requestBody(init?: RequestInit): string {
  return typeof init?.body === "string" ? init.body : "";
}

export type SettingsRequestBody = {
  protocol?: string;
  llm: {
    api_key?: string | null;
    api_key_env?: string;
    model?: string;
    base_url?: string;
    protocol?: string;
  };
  embedding?: Record<string, unknown>;
};

/** 解析设置保存/测试请求体；只声明测试实际断言的字段。 */
export function parseSettingsBody(init?: RequestInit): SettingsRequestBody {
  return JSON.parse(requestBody(init)) as SettingsRequestBody;
}
