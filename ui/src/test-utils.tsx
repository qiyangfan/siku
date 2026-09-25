import { MantineProvider } from "@mantine/core";
import { render as testingLibraryRender, type RenderOptions } from "@testing-library/react";
import type { ReactElement } from "react";
import { cssVariablesResolver, theme } from "./theme";

export function render(ui: ReactElement, options?: RenderOptions) {
  return testingLibraryRender(
    <MantineProvider
      theme={theme}
      cssVariablesResolver={cssVariablesResolver}
      forceColorScheme="light"
    >
      {ui}
    </MantineProvider>,
    options,
  );
}
