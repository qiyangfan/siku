import eslintReact from "@eslint-react/eslint-plugin";
import eslint from "@eslint/js";
import vitest from "@vitest/eslint-plugin";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import testingLibrary from "eslint-plugin-testing-library";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "src-tauri"] },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  jsxA11y.flatConfigs.recommended,
  {
    files: ["**/*.cjs"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.node,
    },
  },
  {
    files: ["**/*.{ts,tsx}"],
    // 类型感知规则：只用 TS 项目做语义检查，JS/CJS 配置文件不纳入 project service
    extends: [
      tseslint.configs.recommendedTypeChecked,
      eslintReact.configs["recommended-typescript"],
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // 结构门禁：complexity 取 ESLint 默认阈值 20；模块行数沿用本仓 1000 行口径。
      complexity: "error",
      "max-lines": [
        "error",
        { max: 1000, skipBlankLines: true, skipComments: true },
      ],
      // react-hooks 推荐集已覆盖 set-state-in-effect（error）；
      // 各视图取数均落到异步续体，effect 体内保持零同步 setState。
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
    },
  },
  {
    // 测试侧门禁：Testing Library 查询/断言惯用法 + Vitest 用例卫生
    files: ["**/*.test.{ts,tsx}"],
    extends: [testingLibrary.configs["flat/react"], vitest.configs.recommended],
  },
);
