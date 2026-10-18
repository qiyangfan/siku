import eslint from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "src-tauri"] },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // react-hooks 7 随 compiler 诊断带入的规则：当前 5 个视图文件共 9 处取数
      // 均为 effect 内 fetch + setState 模式，按官方范式重构（渲染期派生/事件
      // 驱动）属独立行为重构面，不在依赖升级件内吞回归风险。告警留存信号，
      // 待专门重构件逐处清零后恢复 error。
      "react-hooks/set-state-in-effect": "warn",
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    },
  },
);
