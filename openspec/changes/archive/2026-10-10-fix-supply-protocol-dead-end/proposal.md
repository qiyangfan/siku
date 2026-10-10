## Why

待裁项（归档件 `2026-10-01-settings-error-cause-codes` 末项）：`SIKU_LLM_PROTOCOL`
环境变量取值越界时，同一根因引发三处死路——`GET /api/settings` 整体 503 使设置页无法
渲染且无自救入口（env 层优先级高于文件层，保存修不了它）；`PUT` 落盘成功却返回 503
降级错误；`siku serve` fail-fast 使桌面 sidecar 进不到页面，且 LLM 一个通道的配置错误
废掉整个服务（检索等不依赖 LLM 的能力一并不可用）。旧裁决否决过「读取面 200 + 空文件层」，
否的是**数据造假与误就绪**，不是「读取面恒可渲染」本身。

## What Changes

- 就绪判定把「解析结果当数据」：`ask_readiness` 对协议越界不再抛异常，新增稳定
  token 集 `invalid`（如 `llm.protocol`，与 `missing` 同形）；`ready=false`，判定
  仍走请求期同一解析路径——视图说无效 ⇔ 请求期必失败，同源不谎报。请求面（问答/
  检索/探测/CLI）保持既有 503 `invalid_settings` 归一失败，零漂移。
- `GET /api/settings`：文件层可读时 SHALL 恒 200 渲染视图（含 invalid token）；
  文件层两型故障（`invalid_config_file`/`config_file_unreadable`）语义不变。
- `PUT /api/settings`：落盘成功即返回 200 成功响应（视图携带 invalid token 与
  既有事实字段），不再返回 503 降级错误形状；兜底分支保留给未来供给类异常。
- `siku serve` 对协议越界容忍启动（与既有「坏文件不堵启动面」同一规则收敛）：
  stderr 告警点名 `SIKU_LLM_PROTOCOL` 与重启指引，横幅显示通道无效状态；部分可用性
  成立——LLM 通道坏不废检索。CLI 一次性命令保持 fail-fast（shell 里指引用行动）。
- 设置页对 invalid token 展示警示条：说明该值来自环境变量层、保存覆盖不了、给出
  「修正变量 + 重启」指引；SHALL NOT 提供任何「保存可修」入口（旧场景意图保留）。
- 顺手收紧本 change 触及的 5 处主规格超长 Requirement 正文（≤500 字符，细则在场景），
  恢复 `openspec validate --specs --strict` 全绿——纯文本收敛，场景名全保留。
- 遵守 ADR-0009（分层口径）、ADR-0012（多协议）；修订 `validate-supply-values-at-boundaries`
  与 `fix-model-supply-error-surfacing` 两归档件确立的读取面 503 契约（仅协议越界一型）。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `model-supply`：就绪判定新增 `invalid` token 集；协议越界的分面结果（读面 200+标记、
  请求面 503 不变）；serve 容忍启动。
- `http-api`：设置读写端点对协议越界的响应语义（GET 恒 200、PUT 成功形状）。
- `web-ui`：设置页 invalid 警示条与就绪提示适配。

## Impact

`model_supply.py`（readiness）、`api/settings.py`（视图透传）、`api/models.py`
（AskReadinessView 新字段）、`api/app.py`（docstring 与降级分支注释）、`cli.py`
（serve 启动分支）、`ui/src`（类型、SettingsView、LlmReadinessHint）；
`contracts/openapi.json` 再生成（新增可选字段）；测试净增与改判若干。
既有 503 分道（文件层两型）与请求面契约零变化。

## Non-goals（不做清单）

- 不改文件层两型故障的 503 语义与自救入口（刚建成且工作正常，不churn）。
- 不改请求面（问答/检索/探测）与 CLI 一次性命令的 fail-fast 归一失败。
- 不让设置页提供任何修改环境变量的能力（GUI 进程改不了父环境，也不该试图改）。
- 不引入「读取面对文件层错误容忍 200」——旧否决理由（误就绪）继续成立。
- 不动 MCP 工具面（请求面语义已正确）。
- 不做 serve 运行期热感知环境变量变化（重启生效是 env 层固有语义）。
