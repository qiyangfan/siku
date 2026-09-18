# HANDOFF — siku 交接文档

> **接驳点，非常驻知识库。** 常驻知识分属四层：宪法 `openspec/project.md`、协作规范
> `AGENTS.md`、路线 `docs/ROADMAP.md`、相关决策 `docs/adr/`。本文件每次交接整体重写，
> 只写接手者马上需要的状态。

- **更新时间**：2026-09-18
- **仓库**：`~/siku` → github.com/qiyangfan/siku（私有；SSH 推送，gh keyring 认证）

## 现状

- Phase 0/1/2/3 已完成并归档；Phase 4 HTTP API 与问答纵切面均已完成并归档为
  `openspec/changes/archive/2026-09-18-add-http-api-vertical-slice`、
  `openspec/changes/archive/2026-09-18-add-qa-vertical-slice`；主 spec 已同步到
  `openspec/specs/http-api/spec.md` 与 `openspec/specs/web-ui/spec.md`。
- 新增 `src/siku/api/`：`GET /api/health`、`POST /api/ingest`、`POST /api/search`、
  `POST /api/graph`、`POST /api/wiki`；统一领域错误映射、localhost CORS、OpenAPI 快照
  `contracts/openapi.json` 和显式刷新命令。
- 新增 `siku serve`，默认 `127.0.0.1:8000`；`graph`/`wiki` 支持
  `--llm-base-url` 与 `--llm-model`；README 已补 muniu openai 兼容网关的可选说明及
  语义缓存/摘要身份约束。
- 新增 `src/siku/qa/` 与 `POST /api/ask`：复用混合检索，服务端有界打包上下文、校验
  citation、无命中确定性拒答；新增 `ui/` React 单轮问答界面，支持 `siku serve --with-ui`。
- 当前分支：`main`，本地与 `origin/main` 同步于 `7fd99a1`；上一阶段已提交、推送并快进
  合入 main，工作区当前包含本次问答纵切面实现及归档文档，尚未 commit/push。

## 验证

- `uv run pytest`：427 passed（仅 FastAPI/Starlette 与当前 httpx 组合的弃用警告）。
- `cd ui && npm ci && npm run lint && npm test && npm run build`：通过（4 tests）。
- 检索 golden set：Recall@5=1.000、MRR@10=0.95679，与 v0 基线相比无下降。
- `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy`、
  `uv run pre-commit run --all-files` 全部通过。
- `openspec validate --specs --strict`：5/5 通过；当前无 active change。

## 下一步（唯一排序）

- 当前没有已冻结的 active change；后续能力必须先按路线与 ADR 新建 OpenSpec change，
  再进入实现。
- UI 只能经 localhost HTTP API 访问内核；不得读取 vault、SQLite、LanceDB、parquet 或
  图谱缓存，不得把检索、提示词或引用校验业务逻辑放入前端。浏览、图谱画布和 wiki 阅读
  是已完成问答闭环后的后续支撑视图。

## 已知坑

- LanceDB 0.38 新连接的 `list_tables()` 有可见性竞态，向量表探测必须使用 `open_table()`。
- `siku graph` 的 key 校验是惰性的：缓存全命中无需 key；`--rebuild` 需要 key。
- 换 LLM 通道必须同步 graph/wiki 的模型身份；muniu 租户必须关闭语义缓存，否则会破坏
  重建 diff 为空的幂等闸门。
