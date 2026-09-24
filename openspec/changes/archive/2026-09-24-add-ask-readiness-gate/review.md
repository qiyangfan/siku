# 评审：问答就绪门控（add-ask-readiness-gate）

独立子代理评审（2026-09-24），结论 **PASS（阻塞项 0）**。评审范围：本次全部
工作区改动（排除并行任务的 LibraryView/styles.css/SettingsView 凭证 UI）。

## 评审重点证据

1. **判定与请求期同源**：llm 走同一 `resolve_llm_channel` + `resolve_api_key`
   （strip 口径与 `HttpxLlmProvider._resolve_api_key` 逐字一致）；embedding 复用
   同一 `_resolve_channel`，缺项判定与 `resolve_embedding_channel` 的 raise 条件
   逐字段相同；rerank 请求期 `ModelNotAvailableError` 被 `_supply_search_service`
   吞为 reranker=None，与判定侧永不阻塞一致。「判定就绪而请求报未配置」的危险
   方向被排除。
2. **凭证零泄漏**：`AskReadiness`/`AskReadinessView` 仅 `ready: bool` 与三个常量
   token；`resolve_api_key()` 明文只做 `is None` 判断即弃；OpenAPI schema 无凭证
   字段；`test_readiness_never_leaks_key_material` 显式断言。
3. **fail-open 边界**：`normalizeReadiness` 对非对象/ready 非布尔/missing 非数组
   /「未就绪但 missing 为空」矛盾形状一律按不可得（null）→ 不阻塞；置灰时
   Enter 路径被 `submit()` 入口二次校验拦截；「重试问答」按钮同经此闸。
4. **并行任务无冲突**：SettingsView 仅增可选 `onSaved` prop 与 save() 一处回调，
   与 key_mode 分段 UI 正交；PUT 响应经 `SettingsWriteResponse` 继承
   `ask_readiness`，类型链通；vitest 54 全绿。
5. **OpenAPI 快照**：仅新增 `AskReadinessView` schema 与 settings 响应字段，
   无漂移测试通过。
6. **测试覆盖**：http-api delta 4 个 Scenario、web-ui delta 3 个 Scenario 与
   proposal 边界裁决逐条对应（含 CLI 文案不变的守护断言）。
7. **代码规范**：注释/docstring 中文、映射层中文文案与域层英文 message 的既有
   分工保持（0b90c59 先例格局）、类型注解齐全、无 print。

## 评审建议处置（全部采纳）

- token 字面量提为模块常量（`MISSING_LLM_API_KEY` 等）。
- `normalizeReadiness` 增加矛盾形状防御（!ready 且 missing 空 → 不可得）。
- fail-open 用例补「提交后走既有错误路径」断言，Scenario 3 单用例闭环。
- HTTP 面文案改回对冲表述「未配置**或不可用**」：评审指出断言式「尚未配置」
  对「凭证被拒」边缘场景误导放大（见下），对冲表述对该场景诚实。
- design.md 决议 #2 补记 serve CLI 层盲区（`--embedding-base-url` 启动时判定
  偏保守、UI 置灰但请求可成功；危险方向被 CLI 层单调覆盖语义排除；设置中心
  模式下不受影响，消除需透传 CLI 层，随后续 change）。

## 冒烟记录

- 单元/集成：pytest 642（全量）、vitest 54、mypy、ruff、eslint、tsc、build、
  pre-commit 全绿。
- 真实端点冒烟（owner 指定 DASHSCOPE_API_KEY，tmp 语料零污染）：
  - env 层补齐三通道 → serve 启动 → `GET /api/settings` `ready=true`；
    `POST /api/ask` 真实回答 + 1 条引用（qwen-plus）。
  - 清空 env → `ready=false` 且 missing 三项；`/api/ask` 503 友好 UI 导向文案，
    无 config.toml 路径与 CLI 参数。
  - 冒烟中曾复现「CLI index 报未配置」→ 归因不是配置缺失，而是凭证未传时
    DashScope 401 被 `_endpoint_error` 归入 `ModelNotAvailableError`。

## 上报：既有缺陷（非本 change 引入，另行立项）

- **凭证被拒误报为「未配置」**：embedding/rerank 通道 401/403 经
  `retrieve/api_providers.py::_endpoint_error` 抛 `ModelNotAvailableError`，
  CLI 与 HTTP 统一显示「请在 config.toml 补全 base_url 与 model」——此时这两项
  往往已配置，真正问题是 key 被拒。正确修法需从 `ModelNotAvailableError` 分型
  出凭证错误（如 `EndpointCredentialError`），在 map_domain_error / map_ask_error
  / CLI retrieval_error_message 三面加映射与文案，属错误分类体系变更。
- **config.toml 损坏同样落入该误导文案**（load_config 抛同类）：新 HTTP 文案
  引导「去设置页」时 GET /api/settings 也会失败，用户没有下一步；分型时应一并
  给「配置文件损坏」独立指引。建议单开 change 处理。
