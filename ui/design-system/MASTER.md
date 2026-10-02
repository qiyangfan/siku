# siku UI 设计系统基线

## 场景与核心任务

场景是本地知识库工具界面，采用克制模式。用户进入页面 3 秒内应先看到问题输入、提交操作和清楚标为“本地服务”的连接状态；回答与来源依据是第二层重点。可选的提问建议来自已导入笔记章节和 wiki 实体，位于输入区下方，不能盖过主要提问操作。

## Token

`src/theme.ts` 是 token 的单一运行时来源：Mantine theme 定义组件库颜色、字阶、间距和圆角；`cssVariablesResolver` 将相同值提供给领域 CSS。`src/styles.css` 只消费这些变量，不再重复声明 token。主题固定为浅色，通用控件不得另造裸色值或裸尺寸。

| 用途 | Token | Mantine 映射 | 取值/约束 |
|---|---|---|---|
| 主操作与焦点 | `--color-accent`、`--color-accent-strong`、`--color-accent-wash` | `colors.siku[6]`、`colors.siku[7]`、`colors.siku[0]`，`primaryColor: siku` | `#2457d6`、`#173d9d`、`#edf2ff` |
| 正文/辅助文字 | `--color-ink`、`--color-ink-soft`、`--color-ink-faint` | 全局文字、`fontFamily` | 辅助色 `#536174`；弱提示 `#626f81`，白底对比度满足 4.5:1 |
| 表面和边界 | `--color-canvas`、`--color-surface`、`--color-border`、`--color-border-strong` | Provider 的 light scheme 与 `Paper`/`Fieldset` | `#f6f8fb`、`#ffffff`、`#dce3ec`、`#c5cfdd` |
| 边框宽度 | `--border-width`、`--border-width-strong` | 普通边界与强调分隔 | 1px、3px |
| 状态 | `--color-success`、`--color-warning`、`--color-danger` 及 wash/border | `Alert`、`Badge`、`Progress` 的语义色 | 仅表示成功、警告、错误和进度 |
| 图谱分类 | `GRAPH_COMMUNITY_COLORS`、`GRAPH_UNASSIGNED_COLOR` | Sigma 节点颜色 | 按社区编号稳定映射；未分配节点使用中性灰 |
| 字阶 | `--font-display`、`--font-heading`、`--font-subtitle`、`--font-body`、`--font-small`、`--font-caption` | `headings`、`fontSizes` | display 响应式；正文 16px；辅助文字 12px |
| 间距 | `--space-1` 至 `--space-7` | Mantine `spacing`（xs 至 xl）和领域排版扩展 | 固定为 4、8、12、16、24、32、48px |
| 圆角与阴影 | `--radius-sm/md/lg`、`--radius-pill/circle`、`--shadow-card` | Mantine `radius`、`defaultRadius`；`Paper` shadow | 控件 8px、标准卡片 14px、主卡片 20px；胶囊与圆形单独使用 |
| 可交互尺寸 | `--control-height`、`--control-height-mobile-nav`、`--siku-service-badge-height` | Mantine Button、Tabs、Input、Menu、Badge | 常规控件 44px；移动端底部导航 56px；状态气泡 28px |
| 内容宽度 | `--content-max` | `Container size="md"` | 问答与视图共享 52rem 阅读宽度 |

React 界面的设计值集中定义在 `src/theme.ts`；领域 CSS 只消费变量，不再复制数值。扩展 token 时先改该文件，再同步本规范。Tauri 启动/恢复页必须在 sidecar 未启动或已失效时独立显示，因此保留静态 HTML 与原生按钮，并在 `src-tauri/shell-ui/index.html` 镜像其使用到的颜色、字号、间距和控件高度；它不承载应用业务组件。

## 全局尺寸规范

所有尺寸以浏览器根字号 16px 换算。除 0、`auto`、内容宽度和安全区 inset 外，CSS 中的非零间距、字号、行高必须引用 token；边框宽度使用 `--border-width` 或 `--border-width-strong`。组件内不写裸 `px`、`rem` 或未命名比例。

### 间距

| Token | 固定值 | 用途 |
|---|---:|---|
| `--space-1` | 4px | 图标与文字、紧凑标签内部 |
| `--space-2` | 8px | 同组控件、按钮内边距的小档 |
| `--space-3` | 12px | 控件组与表单字段之间 |
| `--space-4` | 16px | 卡片默认内边距、页面水平留白 |
| `--space-5` | 24px | 大卡片内边距、页面区块间距 |
| `--space-6` | 32px | 主要内容区块之间 |
| `--space-7` | 48px | 桌面页面顶部留白 |

Mantine `xs/sm/md/lg/xl` 固定映射为 4/8/12/16/24px。Stack、Group、Paper 的 `gap`/`p` 属性使用这组键；32px、48px 只通过对应 CSS token 使用。margin、padding、gap 不另设局部刻度。

### 字号、行高和字重

| Token | 固定值 | 用途 |
|---|---:|---|
| `--font-caption` | 12px | 状态、辅助信息、移动导航标签 |
| `--font-small` | 14px | 按钮、紧凑列表文字 |
| `--font-body` | 16px | 正文与输入 |
| `--font-subtitle` | 18px | 回答正文、次级标题 |
| `--font-heading` | 22px | 页面区块标题 |
| `--font-display` | 32–56px | 页面主标题，随视口平滑缩放 |

| 行高 Token | 值 | 对应用途 |
|---|---:|---|
| `--line-caption` | 1.4 | 标签与辅助文字 |
| `--line-control` | 1.25 | 按钮、tab 和控件标签 |
| `--line-heading` | 1.3 | 标题 |
| `--line-body` | 1.65 | 正文、输入文字 |
| `--line-reading` | 1.75 | 长回答阅读 |
| `--line-display` | 1.05 | 页面主标题 |

全局字重只有 400、500、600、700、800 五档，分别映射到 `--weight-regular/medium/semibold/bold/display`。组件不得自行增加字重或字号。

### 通用组件尺寸

| 组件 | 高度 | 水平 padding / 组间距 | 字号 / 行高 | 圆角 |
|---|---:|---:|---|---:|
| Button | 最小 44px | 16px | 14px / 1.25；字重 600 | 8px |
| Input、Textarea | 最小 44px | 16px | 16px / 1.65 | 8px |
| Service Badge | 28px | 8px | 12px / 1.4 | 胶囊 |
| 桌面主导航 Tabs | 44px | tab 内 12px、相邻 8px | 14px / 1.25 | 胶囊 |
| 移动底部 Tabs | 56px | 单项间 8px、项内 8px | 12px / 1.25 | 14px |
| 内容卡片 | 内容决定 | 默认 16px；重点阅读卡 24px | 继承所属文字层级 | 行内卡 8px、标准卡 14px、重点卡 20px |

桌面页面外边距为上/下 48px、左右 16px；移动页面顶部 24px、左右 16px，底部为内容留白加导航高度 56px 与设备安全区。触控目标最小 44×44px；移动导航项目为 56px 高。

内容列、断点、画布坐标和安全区属于布局值，可按具体内容调整；它们不能成为额外的通用间距或文字刻度。

## 控件选型

| 数据 | 控件 | 键盘行为 |
|---|---|---|
| 应用导航 | Mantine Tabs | Tab/方向键切换，暴露选中态与关联面板 |
| 自然语言问题 | Mantine Textarea | Enter 提交，Shift+Enter 换行 |
| 文本与凭证 | Mantine TextInput、PasswordInput | 使用标签和现有只写凭证语义 |
| 二选一/开关/数值 | Radio.Group、Checkbox、Switch、NumberInput | 状态可访问，数值保持范围校验 |
| 单轮提交与行内动作 | Mantine Button | Tab 聚焦，Enter/Space 执行；主次动作风格统一 |
| 进度与状态 | Alert、Loader、Progress、Badge | 加载、空态、成功和失败有清晰的视觉/辅助技术提示 |
| 危险操作 | Mantine Modal | 焦点困在弹窗内；取消和确认操作明确 |
| 内容容器 | Container、Stack、Group、Paper | 页面宽度、间距、卡片和工具栏保持一致 |
| 来源详情 | 原生 details/summary | 键盘展开与收起，保留浏览器原生语义 |

## 方案自查

核心任务是 API 驱动的单轮问答，输入、状态、答案、引用四个区域直接对应用户判断“回答是否有依据”的路径；导航、设置、资料管理和知识视图共享 Mantine 的表面、间距和动作约定；没有加入会话、账户或远程服务等超出范围的工作流。
