# 任务清单

## 1. 工具与配置

- [x] 1.1 安装 prettier/stylelint/jsx-a11y/dependency-cruiser/knip/jscpd/coverage-v8。
- [x] 1.2 新增 `.prettierignore`、`.stylelintrc.json`、`.dependency-cruiser.cjs`、
  `.jscpd.json`、`knip.json`、`.npmrc`；补 package.json 脚本。
- [x] 1.3 `.npmrc` 设 legacy-peer-deps（jsx-a11y 未声明 ESLint 10 peer）。

## 2. 存量清零

- [x] 2.1 prettier 格式化 31 个文件；`format:check` 通过。
- [x] 2.2 stylelint 84 → 0（供应商类模式、自动修复、顺序调整、2 处逐条注释禁用）。
- [x] 2.3 jsx-a11y 4 个错误 → 0（点击委托逐条注释禁用）；9 条既有 react-hooks warning 保留。
- [x] 2.4 knip：移除 6 个未使用 default export、8 个未使用导出类型；死代码 0。
- [x] 2.5 vitest 覆盖率阈值落地（79/75/81/79）。

## 3. 门禁接线与验收

- [x] 3.1 ci.yml ui job 串接 8 道检查 —— actionlint 通过。
- [x] 3.2 depcruise：0 error / 1 warn（vite-env.d.ts orphan）。
- [x] 3.3 jscpd：34 clones、4.63%，阈值 5.2% 通过。
- [x] 3.4 test:cov：133 passed，阈值通过。
- [x] 3.5 `npm run build` 通过。
- [x] 3.6 `openspec validate 2026-11-19-add-web-quality-gates --strict` 通过。

## 4. 结构门禁

- [x] 4.1 eslint 启用 `complexity`（默认 20）与 `max-lines`（1000）。
- [x] 4.2 7 处复杂度热点全部 ≤20（App/GraphView/LibraryView/WikiView/SettingsView/preview）。
- [x] 4.3 `LibraryView` 拆出 `LibraryPanels.tsx`（610 + 561 行），`WikiView`/`SettingsView`
  提取模块级子组件；零 eslint-disable。
- [x] 4.4 复验：eslint 0 error、tsc 0、test:cov 133 passed、build 通过。
