# 设计：HTTP API 契约纵切面

## 边界与分层

`src/siku/api/` 只做三件事：**请求模型校验 → 服务层调用 → 响应模型/错误映射**。
不写任何业务计算（红线 #2 的 API 侧镜像：UI 零业务逻辑，API 层同样零业务逻辑）。
服务复用现有入口：`ingest.ingest_path`、`retrieve.service.SearchService`、
`graph.service.build_graph`、`wiki.service.generate_wiki`，均为 Phase 1-3 已验证的
全类型注解服务层，本 change 不改动其行为。

## 端点契约

仅绑定 `127.0.0.1`（红线 1：本地优先；`siku serve` 拒绝 `--host 0.0.0.0` 缺省，
显式传参时告警）。全部端点前缀 `/api`：

| 端点 | 方法 | 请求 → 响应 | 复用服务 |
|---|---|---|---|
| `/api/health` | GET | — → `{status, version}` | — |
| `/api/ingest` | POST | `{source, vault?}` → IngestReport 四计数 | `ingest_path` |
| `/api/search` | POST | `{query, top_k?, candidate_k?}` → `{query, results[]}`（字段与 CLI `--json` 同构：锚点+三段分数） | `SearchService` + 本地模型 |
| `/api/graph` | POST | `{vault?, data_dir?, rebuild?}` → 体检报告（字段与 CLI `graph --json` 同构） | `build_graph` |
| `/api/wiki` | POST | `{data_dir?}` → `{entries, cache_hits, llm_calls, empty_graph}` | `generate_wiki` |

LLM 相关端点（graph/wiki）的错误语义与 CLI 完全一致：key 惰性校验、缓存命中免 key。

## 错误归一映射

响应体统一 `{"code": "<稳定错误码>", "message": "<中文文案>"}`，无裸 traceback。
状态码三分类（design 定稿，实施时任务化）：

| 分类 | 状态码 | 领域错误 |
|---|---|---|
| 状态前置不满足（用户需先做某事） | 409 | IndexUnavailable 系、ModelConfigMismatch、GraphArtifactsMissing、GraphArtifactsStale、GraphStoreCorrupt、BaselineExists |
| 输入/源数据不可处理 | 422 | InvalidQuery、NoteParse 系、NotesDirMissing、GraphExtractionError、GoldenSetError、FixtureMismatch |
| 外部依赖不可用 | 503 | LlmNotConfigured、LlmProvider 系（限流/断连/超长/空返回）、ModelNotAvailable、ProviderError、FtsUnavailable |
| 兜底 | 500 | 其余 GraphError / RetrievalError |

中文文案不另起炉灶：把 `cli.py` 的 `_retrieval_error_message` / `_graph_error_message`
抽到共享模块（如 `siku/api/messages.py`，CLI 反向导入），CLI 与 API 永远同一套文案。
错误码 `code` 为稳定英文串（如 `index_unavailable` / `llm_not_configured`），
供 UI 程序化分支；新增领域错误必须同时登记 code 与映射。

## OpenAPI 契约冻结

`contracts/openapi.json` 入库（与检索 baseline 同款模式）：
- 漂移测试：`create_app().openapi()` 序列化结果与快照逐字节对比，不一致即失败，
  提示显式刷新——契约变更是显式决定，不是实现的副产品；
- 刷新：`uv run python -m siku.api.contract --refresh`（写回快照）；
- 快照文件头注明生成方式与"变更须过 review"。

## CORS 与同源

阶段一 UI 两种宿主：开发期 Vite dev server（跨源）与生产同源静态托管。
`create_app()` 挂 CORS 中间件，allow origins 仅 `http://127.0.0.1:5173`
（Vite 缺省）与 `http://localhost:5173`；生产路径由 `siku serve --with-ui` 挂载
`ui/dist` 静态目录（同源零 CORS）。**不开放公网源**。

## LLM 端点配置面（muniu 评估决议落地）

`graph`/`wiki` 命令新增 `--llm-base-url` / `--llm-model`（缺省值 = 现状
DeepSeek 默认，行为不变），透传给 `HttpxLlmProvider(base_url=, model_id=)`。
注意事项写入文档（README 部署节）：
- 换通道必须同步 `summary_identity=SummaryIdentity(model_id=...)`，否则 wiki 阶段
  按设计抛 `GraphArtifactsStaleError`（真实场景已实证该防护）；
- 经 muniu 时 siku 租户**语义缓存必须关闭**（模糊命中破坏重建 diff 为空的幂等闸门）。

## 测试策略

- 端点契约测试（pytest + httpx ASGI transport，不起真实端口）：给定请求 → 断言
  状态码/响应体/错误码；领域层用既有 fake（ScriptedLlmProvider、FakeEmbeddingProvider）
  注入，CI 永不打真实 API 与真实网络。
- 错误映射表驱动：每个领域错误类 → 断言状态码/code/文案。
- 契约漂移测试 + 显式刷新命令。
- CLI 参数透传测试：fake provider 断言收到 base_url/model_id。
- `siku serve`：工厂模式启动测试（不监听公网断言、拒绝 0.0.0.0 缺省）。
