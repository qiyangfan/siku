# 提案：完成 HTTP API 契约纵切面（Phase 4 契约先行）

## Why

Phase 3 完成后内核能力已齐（摄取/检索/图谱/wiki 全部有服务层入口），但 UI 与内核之间
还没有正式边界。ADR-0002 的红线：**UI ↔ 内核只经 localhost HTTP API，业务逻辑禁止进入
前端或壳**——内核对 UI 形态零假设，三阶段发布路线（localhost WebUI → Tauri → 签名桌面）
才成立。ROADMAP Phase 4 明确"契约先行"：先把 HTTP 契约冻结入库，React UI（浏览/图视图/
对话）作为后续 change 与契约并行开发，永不越界。

另按 muniu 评估决议（2026-09-18）：siku ↔ muniu 不做代码级对接，靠 openai 兼容契约
天然兼容（kongming 同款"两项切换"）；本次补齐 CLI 的 LLM 端点配置面并写入可选部署文档。

## What Changes

- 新增 `src/siku/api/`：FastAPI 应用工厂（`create_app()`），仅绑定 127.0.0.1，
  五个端点：`GET /api/health`、`POST /api/ingest`、`POST /api/search`、
  `POST /api/graph`、`POST /api/wiki`（摄取/检索/图谱三端点 + 健康检查 + wiki 生成）。
- 新增 CLI `siku serve`（uvicorn 承载，默认 127.0.0.1:8000，禁止公网绑定缺省）。
- 领域错误 → HTTP 状态码 + 稳定错误码 + 中文文案的归一映射；抽取共享错误文案模块，
  CLI 与 API 复用同一套映射，杜绝两套文案漂移。
- OpenAPI 契约快照冻结入库（`contracts/openapi.json`），漂移测试把门，显式命令刷新。
- CLI `graph`/`wiki` 补 `--llm-base-url` / `--llm-model` 透传（构造函数已支持，
  纯参数面补齐）：任意 openai 兼容端点（muniu/ollama 等）即插即用，默认行为不变。
- 文档：经 muniu 网关的可选部署说明（**语义缓存对 siku 租户必须关闭**——模糊命中会
  破坏重建 diff 为空的幂等闸门）。

## 受影响决策

- ADR-0002：UI ↔ 内核 localhost HTTP 边界的内核侧正式落地（本 change 是 UI 的前提）。
- ADR-0006：openai 兼容通道的配置面从硬编码默认扩展为可配置（默认 DeepSeek 不变）。

## 与项目亮点/路线的关系

本 change 不新增内核能力，只把已有能力（Phase 1-3 的服务层）以 HTTP 契约暴露并冻结，
是 Phase 4 UI（浏览/图视图/对话）的开发前提。检索回归门禁（ADR-0006）不受影响——
API 层零业务逻辑，检索行为不变。

## 本 change 不实现（Deferred，不是产品删项）

- 不做 React UI（浏览/图视图/对话）——后续 change，与本契约并行开发。
- 不做对话/问答编排——UI change 之后另立。
- 不做鉴权、多租户、HTTPS、公网暴露——localhost 单用户（ADR-0002 阶段一）。
- 不做图谱检索通道（图遍历召回）——按需叠加，维持 Backlog。
- 不做 muniu 代码级集成——仅配置层使用 + 文档；muniu 语义缓存对 siku 必须关闭。
- 不改动任何领域层（graph/retrieve/wiki/ingest）行为；API 层零业务逻辑。
