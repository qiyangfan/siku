# 设计：桌面 UI 设置中心（BYOK 三通道端点配置表单）

## 目标拓扑

```text
UI 设置表单（React 视图，App 内 tab 切换，无路由依赖）
  → GET  /api/settings        文件层掩码视图 + env 覆盖标注
  → PUT  /api/settings        校验 → 合并写 config.toml（原子 0600）→ 失效 provider 缓存
  → POST /api/settings/test   单通道最小探测（不持久化、不回显上游错误体）
       ↘ serve 内核：三通道 provider 按新配置在下一次请求时重建（免重启）
```

实现落点：领域逻辑新模块 `src/siku/api/settings.py`（掩码视图/合并/校验/探测/告警），
路由挂进 `api/app.py`；写盘收敛在 `model_supply.save_config`（升级为原子替换）。

## 约束冻结决议 #1：三个设置端点的契约形状

**GET /api/settings → `SettingsResponse`**

```json
{
  "config_path": "/Users/x/Library/Application Support/siku/config.toml",
  "llm": {
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat",
    "api_key_env": "SIKU_LLM_API_KEY",
    "api_key_set": true,
    "env_overrides": ["api_key"]
  },
  "embedding": { "...": "同构" },
  "rerank": { "...": "同构" }
}
```

- 视图一律呈现 **config.toml 文件层** 的值（表单编辑的对象就是文件层）；
  `base_url` / `model` / `api_key_env` 未设置时为 `null`；`api_key_set` 是文件层
  明文 `api_key` 是否已设置的布尔标记；响应任何字段不含 key 明文。
- `env_overrides`：该通道中被 `SIKU_{LLM|EMBEDDING|RERANK}_*` 环境变量层覆盖的
  字段名列表（该字段在 env 层非 None 即视为覆盖，无论文件层是否设置）。llm 通道
  的 DeepSeek 兜底缺省不属于覆盖，不进此列表（视图只呈现文件层，不呈现有效值）。
- `config_path` 帮助用户定位文件层落点（UI 展示为只读提示）。

**PUT /api/settings → 请求 `SettingsUpdateRequest`，响应 `SettingsWriteResponse`**

```json
{ "llm": {"base_url": "...", "model": "...", "api_key": "...", "api_key_env": "..."},
  "embedding": {"...": "同构"}, "rerank": {"...": "同构"} }
```

- **通道粒度部分更新**：`llm`/`embedding`/`rerank` 任一通道对象可省略，省略 =
  该通道文件层保持不变。
- **字段语义（四字段统一）**：字段省略 = 保持文件层现值；字段为 `null` 或空白串
  = 显式清空（空串与未设置等价的全局口径）；非空字符串 = 设置为去空白后的值。
  `api_key` 以 `SecretStr` 承载，只在非空时落盘。
- 响应 = 写入后的掩码视图（同 GET 形状）+ `"warnings": ["..."]` 告警数组。
- 校验失败 → `422 {"code": "invalid_settings", "message": 中文指引}`，config.toml
  不被改写；既有 config.toml 损坏（非法 TOML）→ 沿既有 `model_not_available`
  503 映射。新增稳定错误码仅 `invalid_settings` 一个。
- 校验规则：`base_url` 非空时必须是 http(s) 且带主机的合法 URL；`api_key_env`
  非空时必须匹配 `^[A-Za-z_][A-Za-z0-9_]*$`；`model` 去空白后非空。仅校验本次
  提交的非清空值，不回溯校验文件层既有值。

**POST /api/settings/test → 请求 `SettingsTestRequest`，响应 `SettingsTestResponse`**

```json
// 请求：channel 必填；其余字段省略 = 用当前分层解析后的有效通道配置，
// 非空字段 = 覆盖对应字段（与 PUT 同构，SecretStr 承载 api_key）
{ "channel": "embedding", "base_url": "http://127.0.0.1:11434/v1", "model": "bge-m3" }
// 成功：{ "ok": true, "channel": "embedding", "latency_ms": 83 }
// 失败：503 + {code, message}（复用既有错误码族）
```

- 最小探测负载：llm = 1 次 `chat/completions`（固定探针短语）；embedding = 1 条
  文本 `embeddings`；rerank = 1 query + 1 document `rerank`。均不含任何语料内容。
- 失败映射（复用既有稳定错误码，503）：`LlmNotConfiguredError` →
  `llm_not_configured`；`ModelNotAvailableError`（401/403 凭证拒绝）→
  `model_not_available`；`LlmRateLimitError` → `llm_rate_limited`；
  `LlmConnectionError`（断连/超时）→ `llm_connection_error`；`LlmProviderError`
  及其余未列子类 → `llm_provider_error`（与既有 `map_domain_error` 对该异常类的
  稳定码保持一致）；检索侧 `ProviderError` → `provider_error`。message 为通道
  感知的中文指引。
- **不回显上游错误体**（BYOK 评审 P2 收紧）：探测错误消息只由错误类 + 状态码
  构造，不内嵌 `response.text`；路由日志只记 `error_class`，不记异常详情与请求体。

**OpenAPI 快照刷新**：实现完成后 `uv run python -m siku.api.contract --refresh`
显式刷新；变更仅限本 change 三个新增端点（外加 CORS allow_methods 增加 `PUT`，
不改变响应契约形状）。

## 约束冻结决议 #2：rerank 可选语义与 embedding 变更告警

- **留空 = rerank none 的写入形状**：表单不填 rerank 通道（或清空其字段）时，
  PUT 后文件层 rerank 段为空 → 分层解析走既有 `ModelNotAvailableError` → 检索
  服务按 reranker=none（RRF-only）装配。无需任何显式 `enabled=false` 字段，
  「可选一等」语义完全由「段为空 = none」承载。
- **模型身份变更的比对基准**：保存成功后，读 `data_dir` 下索引元数据
  （`SqliteIndex.open_if_exists` + `IndexModelMetadata.from_meta_dict`，缺失或
  损坏时静默跳过——告警尽力而为，绝不阻塞保存）；与 **保存后分层解析的有效
  embedding `model_id`**（env 层参与合并，CLI 层不参与——设置中心不感知 CLI）
  比对 `embedding_model_id`。不一致时返回告警：

  > embedding 模型身份已变更（{旧} → {新}）：已有索引与新模型不兼容，请执行
  > `siku index --rebuild` 全量重建索引后，检索与问答才会按新模型执行。

  仅比对 `model_id`：dimensions 覆盖不属表单字段（检索时既有
  `ModelConfigMismatchError` 409 语义兜底）；不自动触发重建（Non-goals）。

## 约束冻结决议 #3：config.toml 写入策略

- **原子替换**：`save_config` 改为同目录 `tempfile.mkstemp`（0600）→ 写入 +
  flush + fsync → `chmod 0600` → `os.replace`；失败时清理临时文件。并发读者
  （检索请求的分层解析）只会看到完整旧文件或完整新文件，不会读到半截 TOML。
- **0600 权限保持**：临时文件以 0600 创建并在替换前 chmod 收敛，已存在文件被
  外部放宽权限的场景同样被覆盖（行为与现实现一致，测试固化）。
- **与手工编辑并发的语义**：单用户桌面场景不做文件锁与 mtime CAS；PUT 按请求
  开始时读到的文件层状态做合并，写以最后一次保存为准（last-writer-wins）。
  手工编辑与表单保存交叉时，后写者胜出且两者都产出合法 TOML，无半写状态。

## provider 缓存失效（免重启）

- 检索装配缓存 `_supply_search_factory` 的闭包缓存升级为带 `invalidate()` 的
  进程内缓存对象（`threading.Lock` 串行化装配与失效）；PUT 成功后调用失效：
  关闭旧 `SearchService` 持有的 provider 连接池，下一次检索/问答按新文件层配置
  重建。显式注入 `search_service_factory` 的测试路径不受影响（无缓存可失效）。
- LLM 通道：`answer_provider_factory` / `graph_extractor_factory` /
  `summarizer_factory` 默认工厂改为**每次请求** `resolve_llm_channel(cli 层)`
  现解析（config.toml 每次现读），provider 仍按请求构造、用后关闭（现行为）。
  `create_app` 的 `llm_base_url`/`llm_model`/`llm_api_key` 三参收敛为
  `llm_supply: ChannelValues | None`（CLI 层原样透传，优先级不变）。
- 维度探针缓存按 `(base_url, model)` 键控：换模型自动换键，无需失效。

## UI 形态

- App 内轻量 tab 切换（问答 / 设置），本地 state 实现，不引入路由依赖。
- 设置视图：三通道分区表单（base_url / model / api_key / api_key_env）+ 保存 +
  逐通道「测试连接」；api_key 为 password 输入、只写不回显，已设置时占位
  「已设置——留空保持不变」，配套「清除已保存的 key」勾选项（显式清空入口）。
- 反馈：保存成功/失败中文文案、422 校验错误就地展示、重建告警显著呈现（不误导
  为失败）、env 覆盖字段提示（列出被覆盖字段名）。key 不进 localStorage 与
  任何持久化前端状态。

## 测试与验收策略

- 契约测试先行（`tests/test_api_settings.py`）：GET 掩码/env 标注、PUT 通道省略
  与字段清空语义、422 不落盘、0600 保持、重建告警、缓存失效集成（fake 端点不
  重启生效）、test 五剧本（正常/401/限流/断连/超时）与不回显断言（响应 + caplog
  无 key、无上游错误体）。
- `save_config` 原子写与权限回归（`tests/test_model_supply.py` 扩展）。
- UI 组件测试（vitest + testing-library）：表单回填、保存 payload（未触碰的
  key 不上传）、告警/env 提示/测试按钮反馈、键盘可达。
- 交付门禁：pytest 全量、ruff、mypy、pre-commit、openspec strict、OpenAPI 快照
  仅含本 change 显式新增；serve + UI 手工冒烟记录于 review.md。

## 风险与取舍

- `create_app` 签名收敛（三参 → `llm_supply`）是内部 Python API 变更，HTTP 契约
  零变化；调用方仅 cli.serve 与测试，一并更新。
- LLM 通道每请求现读 config.toml：单用户 loopback 下 TOML 读耗时可忽略；换来
  设置免重启生效的统一语义（与检索通道同机制）。
- 探测调用对付费端点产生一次最小计量请求：设置中心的功能必需，负载固定极小。
