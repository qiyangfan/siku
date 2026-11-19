# 提案：前端质量门禁补齐（批次 8 / P1 Web）

## Why

前端此前只有 ESLint + vitest + 构建三道闸：没有格式化、CSS lint、可访问性规则、
依赖边界、死代码、重复代码与覆盖率阈值。跨仓手顺的 Web 门禁面在本仓缺一整组，
且 31 个 TS/CSS 文件存在格式漂移、`styles.css` 有 84 条样式违规。

## What Changes

- **prettier**：`format` / `format:check`，`.prettierignore`；31 个文件格式化到零漂移。
- **stylelint**：`stylelint-config-standard`；84 条 → 0：
  - `selector-class-pattern` 允许 Mantine 供应商类（`mantine-*`），自定义类仍要求 kebab-case；
  - 6 条 `media-feature-range-notation`、1 条 `comment-empty-line-before` 自动修复；
  - `clip` → `clip-path: inset(50%)`；
  - 重排 3 处选择器顺序；2 处跨组件上下文的 `no-descending-specificity` 逐条注明原因禁用该行。
- **eslint-plugin-jsx-a11y**：接入 recommended；4 处错误（Markdown 容器的点击委托）
  逐条注明「键盘 Enter 同样触发 click 冒泡」后禁用该行。
  插件尚未声明 ESLint 10 peer 范围，`.npmrc` 统一 `legacy-peer-deps=true`。
- **dependency-cruiser**：`no-circular`(error)/`no-dev`(error)/`no-orphans`(warn)。
- **knip**：入口 main/preview；清掉 6 个未使用的 default export 与 8 个未使用的导出类型。
- **jscpd**：基线重复率 4.63%，阈值 5.2%（基线 + 0.5）。
- **vitest 覆盖率**：`@vitest/coverage-v8`（钉 5.0.5 与 vitest 同版本），
  阈值取基线向下取整：语句 79 / 分支 75 / 函数 81 / 行 79。
- **结构门禁**：ESLint `complexity`（工具默认 20）与 `max-lines`（1000，空行/注释不计）。
  实测 7 处复杂度热点（`App` 37、`GraphView` 29、`LibraryView` 50、`WikiView` 35、
  `SettingsView` 内箭头 25、`App` 内箭头 21、`preview` 内箭头 22）已全部降到 ≤20：
  按展示块提取模块级子组件；`LibraryView` 拆出 `LibraryPanels.tsx`（610 + 561 行），
  `WikiView` 提取缺失态与详情面板，`SettingsView` 提取凭证区与测试页脚。
  零 eslint-disable、零阈值调整。
- **CI**：ui job 依次执行 format:check、eslint、stylelint、depcruise、knip、jscpd、
  test:cov、build，任一失败即阻断。

## 受影响决策

只引用、不修改：ADR-0008（门禁加入既有 ui job）。`skip_specs: true`。

## Impact

文件面：`ui/package.json`、`ui/package-lock.json`、`ui/.npmrc`、`ui/.prettierignore`、
`ui/.stylelintrc.json`、`ui/.dependency-cruiser.cjs`、`ui/.jscpd.json`、`ui/knip.json`、
`ui/vite.config.ts`、`ui/eslint.config.js`、`ui/src/**`、`ui/index.html`、
`.github/workflows/ci.yml`。运行时行为不变。

## Non-goals（不做清单）

- 不引入 Playwright/axe 浏览器级 e2e（手顺只要求 kongming/jinguan；本仓壳层 e2e
  已由 Python 侧真实 serve 冒烟覆盖）。
- 不把 `no-orphans` 升级为 error（`vite-env.d.ts` 是类型声明，无import 关系）。
- 不把复杂度阈值压到 10：ESLint 的 `complexity` 默认阈值是 20，本批按工具默认执行；
  如需更严，另行裁决并单独重构。
