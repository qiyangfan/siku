## Why

siku 是聚合层五个前端里唯一 light-only 的界面：`ui/src/main.tsx`、`ui/src/preview.tsx`、`ui/src/test-utils.tsx` 三处 `forceColorScheme="light"` 把主题钉死在亮色；kongming/jinguan/muniu/sunmao 均已亮暗双态。知识库是长时间本地阅读与检索的工具，暗色不是审美偏好，而是低光环境下的基线可用性；四仓都有、唯独四库没有，是聚合层一处客观不一致。

缺口也不是机制缺失：ADR-0011 采纳的 Mantine Core 内建「亮/暗/跟随系统」三态与偏好持久化，`theme.ts` 的 `cssVariablesResolver` 也已预留空的 `dark` 块——缺的只是取值与接线，不需要自造任何主题机制。本提案把暗色做成了 token 层的第二组取值，而不是第二套写法。

## What Changes

- 主题模型与 kongming/sunmao 对齐：默认跟随系统，用户在 header 操作区切换后手动值优先于系统；不提供显式「跟随系统」第三态控件，不新增自造存储键或自研解析逻辑（ADR-0011 库默认即机制）。
- 暗色取值单源落在 `theme.ts` 的 resolver `dark` 块：方案相关 token（canvas/surface/ink/border/accent/语义色/shadow）从两态混用的 `variables` 分流进 `light`/`dark` 两块，`variables` 只保留两态同值的间距/圆角/字阶/行高/度量；页面与组件消费既有 `--color-*` token，零裸色值。
- 首帧防闪烁：两处 HTML 入口（应用 `ui/index.html`、Tauri 壳静态启动页 `ui/src-tauri/shell-ui/index.html`）接入主题初始化脚本；壳静态页补 `prefers-color-scheme` 暗色媒体块与 `color-scheme: light dark`，其自成体系的 `:root` 变量与主应用同源。
- 图谱边线色是 canvas 读不到 CSS 变量而常量化在 TS 的既有例外（`GRAPH_EDGE_COLOR`），改为按当前主题取亮/暗两值；节点社区分类色板本批不动（有标签文字兜底），暗底不可读另立。
- 守卫从单态扩到两态：`design-system.test.ts` 现有「语义色取自 Mantine 色阶、浅底对比 ≥4.5:1」镜像出暗底版——暗色正文/辅助字/语义核心色对 canvas 与 surface 一律 ≥4.5:1，暗 wash 上的文字（浅色阶位）对暗 wash ≥4.5:1；切换入口与初始态有组件测试。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `web-ui`：新增「主题三态与两态对比度」需求（界面行为口径，不绑框架）。

## Impact

`ui/src/theme.ts`（resolver 分流 + 暗色取值 + 边线色取值函数）、`ui/src/main.tsx`（provider 默认跟随系统）、`ui/index.html` 与 `ui/src-tauri/shell-ui/index.html`（初始化脚本 + 壳媒体块）、`ui/src/App.tsx`（header 切换入口）、`ui/src/GraphCanvas.tsx`（边线色随主题）、`design-system.test.ts`（两态守卫）与新增切换入口组件测试。零后端/契约/存储变更，零新依赖（ADR-0011 已锁定组件库）。

## Non-goals（不做清单）

- 不做每页面/每组件暗色覆写：暗色一律经 resolver token 分流，任何裸色值即回归。
- 不自造主题存储/解析/上下文：库内建三态与持久化即默认；新增存储键、自研 hook、自写媒体查询监听均不做。
- 不提供显式「跟随系统」第三态入口：两态图标切换 + 系统初值，与 kongming/sunmao 现行口径一致。
- 不动图谱社区分类色板、既有间距/字阶/圆角刻度与 shell 启动页信息结构。
- 不改检索、摄取、HTTP 契约、存储任何行为；不为暗色新增设置项（主题是界面态，不是模型端点配置）。
