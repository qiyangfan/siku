# 实现评审记录

**状态：实现与验证完成，最终独立代码审查通过。**

## 实现结果

- Tauri 在 sidecar 健康后监视托管子进程和 `/api/health`；进程退出或连续五次健康检查失败后回收服务并进入本地恢复页。
- 恢复页由用户选择“重新启动本地服务”；操作触发现有启动编排，健康检查通过后再回到应用。
- 恢复监视器按启动代际校验服务归属，避免旧监视器停止新进程；关闭窗口会使旧监视器失效。
- 浏览器/Vite 模式说明页面不能启动系统进程，提示在终端运行 `siku serve --with-ui`；按钮仅重试连接。Tauri 模式保留真正的重启动作。
- 前端全局状态称为“本地服务”，健康时显示“服务正常”，断开时显示“服务未连接”；离线卡片不限制用户浏览其他视图。

## 验证

- `cargo fmt --check`、`cargo check --locked`：通过；`cargo test --locked`：9 个测试通过，包含关闭请求去重、恢复 URL 清理与恢复状态识别。
- `npm test -- --reporter=dot`：9 个文件、83 个测试通过；包含离线提示、连接检查及恢复状态相关行为覆盖。
- `npm run lint`：通过。
- `npm run build`：通过；JS chunk 779.64 kB（gzip 232.63 kB），超过 Vite 建议阈值但不阻断构建。
- 375px 与 320px 移动预览中，服务状态、三项主导航和浏览/设置视图均无横向溢出；桌面进程恢复及关闭并发语义由 Rust 测试覆盖。
- `openspec validate --changes --strict`：3 个 change 通过；`openspec validate --specs --strict`：8 份规格通过。
- `git diff --check`：通过。

## 独立代码审查

- 首轮最终审查发现重复关闭窗口事件可启动多个清理线程：第二线程可能在首线程的宽限期内销毁窗口，使 sidecar 后代来不及被强制回收。
- `SidecarRegistry::try_begin_shutdown` 现只允许第一个关闭事件取得清理任务；重复事件继续阻止 Tauri 默认关闭，并等待首个任务销毁窗口。新增 `repeated_close_requests_start_only_one_shutdown_task`。
- 修复后的最终独立复审未发现遗留代码问题。隔离审查环境不能绑定 loopback 临时端口，本机 Rust 9/9 通过；Windows 交叉检查受 macOS 缺少第三方 `ring` 所需的 `assert.h` 阻塞。

## 2026-09-25 复审补充

- 健康检查现在解析 JSON 顶层 `status` 字段，不依赖 JSON 紧凑序列化；新增空格格式、嵌套字段、失败状态和非 JSON 回归用例。
- 新增测试首次未通过 `cargo fmt --check`，已按 rustfmt 修复并从格式检查重跑；`cargo fmt --check`、`cargo check --locked`、`cargo test --locked`（11/11）全部通过。
- 自动代码审查未返回结论（zread MCP 握手缺少 `content-type`）；本轮继续检查启动、恢复、代际隔离和关窗清理路径，未发现新的运行期缺陷。
