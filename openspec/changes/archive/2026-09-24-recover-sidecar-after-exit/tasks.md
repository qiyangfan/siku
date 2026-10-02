# 任务清单

- [x] 完成 proposal、design 与 desktop-shell spec delta，并通过 OpenSpec strict 校验。
- [x] 实现 Rust sidecar 运行期监视、退出/连续健康失败恢复页导航与状态区分。
- [x] 将启动失败与运行期恢复页操作明确命名为“重新启动本地服务”，保留退出操作。
- [x] 将 React 全局状态与离线说明改为准确的“本地服务”文案；各视图都能看到状态，浏览器按钮只检查连接并保留 CLI 启动指引。
- [x] 为恢复 URL/状态识别补充 Rust 单元测试，为离线按钮行为补充 React 测试。
- [x] 完成相关 Rust/React 编译、测试和 lint 检查，并将结果记录在 review.md。
- [x] 执行代码审查，核对无残留 sidecar、无网页 IPC 和恢复状态无错误重启，将证据记录在 review.md。
