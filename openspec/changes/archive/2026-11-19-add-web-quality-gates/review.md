# 评审记录：前端质量门禁

## 验证证据（本机实测，npm 26 / Node 26；CI 用 Node 24）

| 项 | 结果 |
|---|---|
| `npm run format:check` | 通过（coverage/dist/lock/src-tauri 已忽略） |
| `npm run lint`（eslint） | **0 error** / 9 warning（既有 `react-hooks/set-state-in-effect`） |
| `npm run lint:css`（stylelint） | 0（84 → 0） |
| `npm run lint:arch`（depcruise） | 0 error / 1 warn（`vite-env.d.ts` orphan） |
| `npm run lint:dead`（knip） | 0 |
| `npm run lint:dup`（jscpd） | 33 clones，**4.46%** ≤ 阈值 5.2% |
| `npm run test:cov` | 133 passed；覆盖率 80.33/75.71/82.41/80.1 ≥ 79/75/81/79 |
| `npm run build` | tsc + vite 通过 |
| `npm ci --dry-run` | 通过（lock 与 package.json 一致） |
| eslint `complexity`（默认 20） | **0 命中**（原 7 处：App 37、GraphView 29、LibraryView 50、WikiView 35、SettingsView 箭头 25、App 箭头 21、preview 箭头 22） |
| eslint `max-lines`（1000） | 0 命中（最大 LibraryPanels 561 行） |

## 存量处置

- prettier：31 个文件格式化到零漂移；`index.html` 内联主题脚本加 `prettier-ignore`
  （被 `design-system.test.ts` 逐字比对）。
- stylelint：供应商类模式放行 `mantine-*`；自动修复 range notation / 注释空行；
  `clip` → `clip-path: inset(50%)`；3 处选择器重排；2 处跨上下文
  `no-descending-specificity` 逐行注明原因禁用。
- a11y：Markdown 只读容器的点击委托 2 处逐行注明「键盘 Enter 同样触发 click 冒泡」。
- knip：删除 6 个未使用 default export、8 个未使用导出类型；`LibraryRunningStatus`
  保持模块内私有。
- 复杂度重构：App/GraphView/LibraryView/WikiView/SettingsView/preview 提取模块级
  子组件；`LibraryView` 拆出 `LibraryPanels.tsx`（610 + 561 行）。零 eslint-disable。

## 保留判断

- `@vitest/coverage-v8` 钉 5.0.5 与 vitest 同版本（5.1.1 混用直接报错）。
- jsx-a11y 6.10.2 未声明 ESLint 10 peer：`.npmrc` 统一 `legacy-peer-deps=true`，
  本地与 `npm ci` 同解析；规则实测生效。
- 显式补装 `graphology-types`（graphology 的 peer，legacy 模式不会自动安装）。
- 不引入 Playwright/axe（手顺仅要求 kongming/jinguan）。

## 遗留

- 外部 CI 未绿（账号账单锁定），change 保持 active。
