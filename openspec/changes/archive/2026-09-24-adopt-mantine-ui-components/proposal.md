# 提案：采用 Mantine 迁移通用 UI 控件

## Why

当前 UI 基础按钮、表单、布局和反馈控件分散在各视图与 CSS 中自行实现。用户明确要求优先使用成熟组件库，避免继续手工重做通用控件。采用 Mantine 后可以统一常见控件的状态、键盘交互和主题配置，减少跨视图重复维护。

## What Changes

- 在 React/Vite UI 中引入 Mantine Core 9.x，并在应用根入口配置共享主题。
- 将现有 CSS 设计 token 集中记录到 `ui/design-system/MASTER.md`，并映射到 Mantine theme；保留蓝色主色、语义色、字阶、4/8 间距、圆角与阴影，并加深次级/占位灰以满足对比度底线。
- 按视图逐步将通用布局、按钮、输入、导航和状态反馈迁移到 Mantine 组件。
- 移除已被组件库替代的通用 CSS 规则，保留产品专属布局、Sigma 图谱画布和 Markdown 安全渲染样式。
- 保持既有视图行为、API 调用、错误语义和交互状态不变。

## 受影响决策

- **ADR-0011**：规定 Mantine Core 作为通用 UI 组件库及其职责边界。
- **ADR-0001**：组件库分发方式局部由 ADR-0011 取代，双栈、React/Vite 与 Sigma.js 技术选择保持不变。
- **架构红线 1**：UI 仍只通过 localhost HTTP API 与内核通信。

## 与项目路线的关系

本项列为 `docs/ROADMAP.md` 当前排序队列中的 UI 维护性工作；它不增加新的产品能力，也不改变 Phase 5 的发布范围。

## 不做清单（Non-goals）

- 不修改 Python 内核、HTTP API、OpenAPI 契约、数据结构或业务流程。
- 不改变 Sigma.js + graphology 图谱画布，也不替换 `ui/src/markdown.ts` 的安全渲染链路。
- 不改变路由、页面信息架构、Tauri 壳或发布策略。
- 不引入 Tailwind、Emotion 或第二套通用组件库。
- 不为通用按钮、输入、弹窗、导航或反馈控件编写项目自有替代实现。

## 规格处理

此项是组件实现层重构，保持现有用户可观察行为不变，不新增或修改 spec requirement；由本 change 的 `.openspec.yaml` 声明 `skip_specs: true`。
