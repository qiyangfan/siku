# siku UI 设计系统基线

## 场景与核心任务

场景是本地知识库工具界面，采用克制模式。用户进入页面 3 秒内应先看到问题输入、提交操作和当前内核状态；回答与来源依据是第二层重点。

## Token

- 主色：`--color-accent` / `--color-accent-strong`，用于主操作、链接和焦点环。
- 辅助色：`--color-ink-soft` / `--color-ink-faint`，用于解释文字和元信息。
- 语义色：`--color-success`、`--color-warning`、`--color-danger` 及对应 wash 背景，只用于连接、警告和错误状态。
- 字阶：`--font-display`（标题）、`--font-body`（正文）、`--font-caption`（辅助信息）。
- 间距：`--space-1` 至 `--space-7`，以 4/8 基础尺度递进。
- 圆角：`--radius-sm`、`--radius-md`、`--radius-lg`。
- 阴影：`--shadow-card`，仅用于主要卡片层级。
- 控件：`--control-height` 保证按钮与触控目标不小于 44px。

实现文件 `src/styles.css` 是 token 的唯一运行时来源；组件不得新增裸色值或裸尺寸。

## 控件选型

| 数据 | 控件 | 键盘行为 |
|---|---|---|
| 自然语言问题 | 多行文本框 | Enter 提交，Shift+Enter 换行 |
| 单轮提交/重试 | 原生 button | Tab 聚焦，Enter/Space 执行 |
| 来源详情 | 原生 details/summary | 键盘展开与收起 |

## 方案自查

核心任务是 API 驱动的单轮问答，输入、状态、答案、引用四个区域直接对应用户判断“回答是否有依据”的路径；没有加入会话、账户、模型 key 或远程地址等超出范围的控件。
