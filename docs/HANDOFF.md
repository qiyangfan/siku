# HANDOFF — siku 交接文档

> **接驳点，非常驻知识库。** 常驻知识分属四层：宪法 `openspec/project.md`、协作规范
> `AGENTS.md`、路线 `docs/ROADMAP.md`、相关决策 `docs/adr/`。本文件每次交接整体重写，
> 只写接手者马上需要的状态。

- **更新时间**：2026-09-18
- **仓库**：`~/siku` → github.com/qiyangfan/siku（私有；SSH 推送，gh keyring 认证）

## 现状

- Phase 0/1/2/3 已完成并归档，Phase 4 内核侧 HTTP API 契约已完成并归档为
  `openspec/changes/archive/2026-09-18-add-http-api-vertical-slice`；主 spec 已同步到
  `openspec/specs/http-api/spec.md`。
- 新增 `src/siku/api/`：`GET /api/health`、`POST /api/ingest`、`POST /api/search`、
  `POST /api/graph`、`POST /api/wiki`；统一领域错误映射、localhost CORS、OpenAPI 快照
  `contracts/openapi.json` 和显式刷新命令。
- 新增 `siku serve`，默认 `127.0.0.1:8000`；`graph`/`wiki` 支持
  `--llm-base-url` 与 `--llm-model`；README 已补 muniu openai 兼容网关的可选说明及
  语义缓存/摘要身份约束。
- 当前本地分支为 `feature/phase4-http-api`，实现已完成但尚未 commit/push。

## 验证

- `uv run pytest`：408 passed（仅 FastAPI/Starlette 与当前 httpx 组合的弃用警告）。
- `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy`、
  `uv run pre-commit run --all-files` 全部通过。
- `openspec validate --changes --strict` 与 `openspec validate --specs --strict` 归档前均通过。

## 下一步（唯一排序）

- 为 React 浏览/图视图/对话另立 change；UI 只能经 localhost HTTP API 访问内核，业务逻辑
  不得进入前端或 Tauri 壳。UI 评审使用 `ui-quality-gate`。
- 提交前保留当前未提交改动并重新检查 `git diff --check`；未经明确授权不 push。

## 已知坑

- LanceDB 0.38 新连接的 `list_tables()` 有可见性竞态，向量表探测必须使用 `open_table()`。
- `siku graph` 的 key 校验是惰性的：缓存全命中无需 key；`--rebuild` 需要 key。
- 换 LLM 通道必须同步 graph/wiki 的模型身份；muniu 租户必须关闭语义缓存，否则会破坏
  重建 diff 为空的幂等闸门。
