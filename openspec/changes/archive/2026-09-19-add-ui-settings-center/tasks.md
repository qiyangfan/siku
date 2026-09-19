# 任务清单

## 约束冻结（实现前）

- [x] 冻结三个设置端点的契约形状：路径、请求/响应字段、掩码表示（key 是否已设）、
      告警结构、新增稳定错误码清单与 OpenAPI 快照刷新方式。
      （决议见 design.md「约束冻结决议」#1）
- [x] 冻结 rerank 可选语义与 embedding 变更告警的表单表达：留空 = none 的写入形状、
      模型身份变更的比对基准与中文指引文案。（决议见 design.md「约束冻结决议」#2）
- [x] 冻结 config.toml 写入策略：原子替换（临时文件 + rename）、0600 权限保持、与
      手工编辑并发的语义。（决议见 design.md「约束冻结决议」#3）

## 内核与 API

- [x] 先写契约测试：GET 掩码不回显 key、PUT 校验失败 422、写入后文件保持 0600；
      再实现 `GET/PUT /api/settings`。
- [x] 实现 serve provider 缓存失效：设置写入后下一次请求按新配置重建 provider；
      补不重启生效的集成测试（fake 端点）。
- [x] 实现 `POST /api/settings/test`：单通道最小连通性调用，复用 provider 错误映射
      （fake 五剧本：正常/401/限流/断连/超时），不回显上游错误体。
- [x] PUT 合并语义与告警：部分字段更新、显式清空字段、embedding 模型身份变更返回
      重建索引告警；补请求体不落日志的断言。
- [x] 刷新 OpenAPI 快照并确认契约测试通过；`/api/health` 等既有端点零漂移。

## UI

- [x] 设置视图骨架：App 内可达的入口与三通道分区表单（base_url/model/api_key/
      api_key_env），key 只写输入与「已设置」占位。
- [x] 保存与反馈：PUT 提交、中文成功/失败文案、校验错误就地展示、重建索引告警显著
      呈现、env 覆盖字段提示。
- [x] 连通性测试按钮：单通道测试、进行中禁用重复点击、结果中文反馈。
- [x] 可访问性与窄窗口：主要操作键盘可达，表单窄窗口不产生不可用溢出；
      `npm run lint/test/build` 全绿。

## 交付门禁

- [x] pytest 全量、ruff check/format、mypy、pre-commit、openspec strict 全绿；
      OpenAPI 快照仅含本 change 显式新增。
- [x] 桌面手工冒烟：表单配置三通道 → 保存 → 不重启直接问答成功；key 在 UI/日志/
      契约示例中不回显；结果记录于 review.md。
      （以 serve + 构建版 UI + 回环 fake BYOK 端点的自动化浏览器冒烟完成；Tauri 壳内
      真实端点手工冒烟留待用户按需执行，见 review.md「冒烟记录」）
- [x] 完成独立 review.md：记录凭证边界、原子写与权限保持、缓存失效与告警语义证据。
