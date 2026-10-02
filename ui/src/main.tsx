import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MantineProvider } from "@mantine/core";
import "@mantine/core/styles.css";
import App from "./App";
import { cssVariablesResolver, theme } from "./theme";

// 主题三态：默认跟随系统；手动切换值经库默认存储键持久化并优先于系统。
// 首帧防闪烁由 index.html 内联的库初始化脚本负责（写 data-mantine-color-scheme）。
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider theme={theme} cssVariablesResolver={cssVariablesResolver} defaultColorScheme="auto">
      <App />
    </MantineProvider>
  </StrictMode>,
);
