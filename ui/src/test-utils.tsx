import { MantineProvider } from "@mantine/core";
import { render as testingLibraryRender, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { cssVariablesResolver, theme } from "./theme";

type ColorScheme = "light" | "dark";

function withProvider(
  ui: ReactElement,
  providerProps:
    | { forceColorScheme: ColorScheme }
    | { defaultColorScheme: "auto" },
  options?: RenderOptions,
) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MantineProvider theme={theme} cssVariablesResolver={cssVariablesResolver} {...providerProps}>
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
export function renderInColorScheme(ui: ReactElement, colorScheme: ColorScheme, options?: RenderOptions) {
  return withProvider(ui, { forceColorScheme: colorScheme }, options);
}

/** 跟随系统入口（auto，不固定）：主题接线与切换入口测试用。 */
export function renderAuto(ui: ReactElement, options?: RenderOptions) {
  return withProvider(ui, { defaultColorScheme: "auto" }, options);
}
