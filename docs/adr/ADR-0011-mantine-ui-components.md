# ADR-0011：采用 Mantine Core 作为通用 UI 组件库

- **状态**：已接受
- **日期**：2026-09-24
- **影响**：局部替代 ADR-0001 中关于通用 UI 组件分发方式的选择；Python/TypeScript 双栈、React/Vite、Sigma.js 与 graphology 决策保持有效。

## 背景

Siku 的 UI 使用 TypeScript、React 19 与 Vite。现有视图自行组合原生按钮、表单元素和项目 CSS；继续复制这些基础控件会增加跨视图的一致性、无障碍和维护成本。项目要求优先使用成熟组件库，避免手工重做通用控件。

现有 `ui/package.json` 将 React 解析到 19.3.0。Mantine Core 9.0.0 声明兼容 React 与 React DOM `^19.2.0`，并提供 Vite 集成指南；默认接入方式是导入 Core 样式并在应用根部挂载 `MantineProvider`。参见 [Mantine Vite 指南](https://mantine.dev/guides/vite/) 和 [Mantine Core 9.0.0 包信息](https://www.npmjs.com/package/@mantine/core/v/9.0.0)。

## 决策

1. 通用界面控件和布局采用 Mantine Core 9.x；`@mantine/core` 与其 peer dependency `@mantine/hooks` 使用一致的 9.x 版本，并由 `package-lock.json` 锁定具体版本。
2. 在 UI 根入口导入 `@mantine/core/styles.css`，通过单一 `MantineProvider` 配置全局主题。现有 CSS token 映射到 Mantine theme 并记录在 `ui/design-system/MASTER.md`；首期使用 Mantine 自带样式，不额外引入 Tailwind 或 Emotion。
3. 常规按钮、输入、表单状态、导航、布局、弹窗和反馈使用 Mantine 组件。不得在项目内重新实现相同职责的基础控件；产品专属交互可组合 Mantine 组件实现。
4. 图谱画布继续由 Sigma.js + graphology 负责；Markdown 继续通过 `ui/src/markdown.ts` 的 marked + DOMPurify 安全渲染。组件库不承接这两类专用呈现逻辑。
5. 维持 UI 与内核只通过 localhost HTTP API 通信的边界，不改变 API、业务流程和持久化契约。

## 理由

- Mantine 是由 npm 依赖提供的组件库，覆盖常见布局、表单与反馈控件，适合以增量方式替换重复的手写控件。
- 当前 React 版本满足 Mantine Core 9.0.0 的 peer dependency，官方文档提供 Vite 接入方式。
- shadcn/ui 的官方 CLI 将选取的组件源码添加到应用中；这种源码分发方式会把控件实现留在项目内维护，不符合本次“使用成熟库提供通用控件”的明确目标。参见 [shadcn CLI 文档](https://github.com/shadcn-ui/ui/blob/main/skills/shadcn/cli.md)。
- Mantine 的主题与组件可以集中管理，保留现有 React、Vite 和 Tauri 技术边界，不需要改变内核依赖。

## 代价与风险

- UI 增加 `@mantine/core`、`@mantine/hooks` 及其样式资源；应在迁移后检查构建产物和 Tauri 启动体验。
- Mantine 默认样式可能与现有 CSS 选择器冲突。迁移按视图逐步进行，删除规则前确认其没有覆盖 Sigma 画布、Markdown 正文或产品专属状态。
- 测试挂载 Mantine 组件时需要统一测试包装器，并继续以可访问角色和标签验证交互，避免测试依赖实现细节。
- Mantine 主版本升级可能调整组件 API；依赖升级必须同步运行 UI lint、测试和构建。

## 复核信号

- 若 Mantine 样式与现有视图无法在合理范围内共存，或 UI 构建与桌面启动成本显著增加，重新评估主题覆盖范围或组件库选择。
- 若后续需求出现专用组件，先检查 Mantine 是否已提供合适组件；只有明确的产品领域行为才新增项目级组件。
