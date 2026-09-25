# 实现评审记录

**状态：实现与验收完成，最终独立代码审查通过。**

## 实现结果

- 接入 Mantine Core 9.x 与 hooks，由根 Provider 提供主题；颜色、圆角、阴影与控件尺寸映射到 `ui/design-system/MASTER.md` 的设计 token。
- 应用外壳、问答、设置、资料库、浏览、wiki 和图谱外围控件统一使用 Mantine；Sigma/graphology 画布和 Markdown 安全渲染保留。
- 桌面导航保留六个视图；移动端在 React 结构中只渲染问答、浏览、图谱三个底部入口，其余视图从顶栏更多菜单打开，避免隐藏入口仍参与键盘导航。
- 本地服务状态使用“服务正常 / 服务未连接”；离线提示说明浏览器模式不能启动系统进程，提供 `siku serve --with-ui` 命令和连接检查入口。
- 搜索行在 375px 与 1280px 宽度下输入框和按钮高度为 44px 且底边对齐；移动端主底栏 375px 宽度下高 65px，页面无横向溢出。
- 建议按钮、菜单和表单操作采用 Mantine 控件；菜单触控项最小高度 44px，键盘焦点可见，保留 reduced-motion 样式。

## 验证

- `npm test -- --reporter=dot`：9 个文件、83 个测试通过。
- `npm run lint`：通过。
- `npm run build`：TypeScript 与 Vite 构建通过；JS chunk 779.64 kB（gzip 232.63 kB），超过 Vite 500 kB 建议阈值但不阻断构建。
- `cargo fmt --check`、`cargo check --locked`：通过；`cargo test --locked`：9 个测试通过。
- `openspec validate --changes --strict`：3 个 change 通过；`openspec validate --specs --strict`：8 份规格通过。
- 375px 与 320px 浏览器预览的 `scrollWidth` 均等于视口宽度；问答输入宽 309px/254px，长建议按钮可换行，三项底栏完整可见且高 65px。更多视图菜单可打开 wiki、资料库和设置；44px 更多按钮可点击，切换到浏览和设置后也无横向溢出。
- 桌面搜索行与输入框此前在 375px、1280px 下确认高度 44px 且底边对齐；文本对比度最低 4.80:1，焦点可见并支持 reduced-motion。
- `git diff --check`：通过。

## 独立代码审查

- 共发现并修复 4 项问题：空语料的 `wiki_missing` 被误判为推荐来源失败；隐藏的桌面导航项仍可被键盘导航激活；健康检查没有请求超时；重复关闭窗口事件可能在 sidecar 进程组强制回收前销毁窗口。
- 导航现改为窄屏只渲染三个 Mantine Button，并从 Mantine Menu 提供其他视图；健康探测 3 秒后由 `AbortController` 取消；关闭清理由首个事件独占，重复事件等待首个任务销毁窗口。
- 修复后的最终独立复审未发现遗留代码问题。复审隔离环境不能绑定 loopback 临时端口，本机 `cargo test --locked` 9/9 通过；Windows 交叉检查受 macOS 缺少 `assert.h`（第三方 `ring` 构建依赖）阻塞。

## UI 质量闸门

- 问题输入与提交流程仍为问答页主层级，推荐内容可跳过；建议来自当前语料且点击后只预填完整问题。
- 375px 和 320px 底栏只展示三个常用视图；其他视图从更多菜单到达，菜单项目满足 44px 触控高度。
- 长标题有断行和精简显示文案；实际问答预览及资料库预览没有产生水平滚动。
- 主色与文字使用主题 token；最低文本对比度 4.80:1，键盘焦点可见并支持 reduced motion。
- 空、加载、失败反馈及主要资料库操作由组件测试覆盖。

## 2026-09-25 复审补充

- 按 `ui-quality-gate` 与 `ui-ux-pro-max` 复核导航、通用控件、间距、触控区和窄屏状态；底部导航为 56px 高，tab 间距 8px，设置页 Radio 标签点击区为 44px。
- 实际浏览器视口复核：375px 检查问答、资料库、设置；320px 检查设置、浏览、图谱、wiki；这些页面的文档宽度均与视口宽度一致。长建议文案可换行，底部只显示问答、浏览、图谱三项。
- 1280px 复核资料库导入表单：文件选择控件宽 512px，下面两个操作按钮各宽 252px、间距 8px，均为 44px 高；输入与按钮行对齐，无横向溢出。
- 发现 Markdown 引用线与 Tauri 壳页的边框宽度、spinner 圆角绕过 token，现分别统一为 `--border-width-strong`、`--radius-circle`；设计系统测试覆盖 React 与静态壳页样式。
- `npm run lint`、`npm test -- --reporter=dot`（10 个文件、89 个测试）和 `npm run build` 通过；Vite 报告 JS chunk 788.09 kB（gzip 235.13 kB）超过 500 kB 建议值，但构建成功。
- Tauri `cargo fmt --check`、`cargo check --locked` 和 `cargo test --locked`（11/11）通过；`openspec validate --specs --strict`（8/8）与 `git diff --check` 通过。`--changes` 下没有活动 change，因为相关 change 已归档。
- 自动代码审查命令曾启动，但因 zread MCP 握手缺少 `content-type` 未返回审查结论；本轮继续进行了源码与预览复核，除上述已修复的 token 不一致外，未发现未修复的布局、交互或可访问性问题。
