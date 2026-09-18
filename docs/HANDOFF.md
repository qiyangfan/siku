# HANDOFF — siku 交接文档

> **接驳点，非常驻知识库。** 常驻知识分属四层（按此顺序读，约 5 分钟）：
> 宪法 `openspec/project.md` → 协作规范 `AGENTS.md` → 路线 `docs/ROADMAP.md` →
> 相关决策 `docs/adr/`。本文件每次交接**整体重写**（历史看 `git log`），
> 硬上限 ~60 行：只写"接手者马上需要的状态"，重复常驻文档的内容即为违规。

- **更新时间**：2026-09-18
- **仓库**：`~/siku` → github.com/qiyangfan/siku（私有；SSH 推送，gh keyring 认证）

## 现状

- **Phase 0/1/2/3 全部完成并合入 main**（CI 绿）。Phase 3 归档
  `2026-09-18-add-graph-wiki-vertical-slice`，graph-wiki spec 已同步；**双通道真实
  冒烟均通过**（DeepSeek 10 次调用、Qwen qwen-plus 11 次调用，二轮零调用全缓存命中，
  幂等闸门双通道成立）。全仓 369 测试绿，mypy/ruff/pre-commit/openspec strict 全过。
- **Phase 4 已 propose 待 apply**：`openspec/changes/add-http-api-vertical-slice/`
  全件（proposal/design/specs/http-api/tasks，13 项）已过 strict 校验，**未写任何
  行为代码**。范围 = FastAPI 五端点契约（health/ingest/search/graph/wiki）+ 领域错误
  → HTTP 归一映射 + OpenAPI 快照冻结（`contracts/openapi.json`）+ `siku serve` +
  CLI `--llm-base-url/--llm-model` 透传（muniu 评估决议落地）。
- **muniu 评估决议（2026-09-18）**：不做代码级对接，靠 openai 兼容契约两项切换
  （kongming 同款）；参数透传并入本 change；**经 muniu 时 siku 租户语义缓存必须
  关闭**（模糊命中破坏幂等闸门）——已写入 change 任务与 spec 场景。

## 下一步（唯一）

新会话从 main 派生 `feature/phase4-http-api`，**apply**
`add-http-api-vertical-slice/tasks.md`（13 项，测试先行，粒度 ≤2h）：应用工厂 →
错误映射 → 四个 POST 端点 → 契约快照 → `siku serve` → CLI 透传 → muniu 文档 →
全量门禁 + review.md + 归档同步 http-api spec。完成后 React UI（浏览/图视图/对话）
另立 change（UI 评审走 ui-quality-gate 闸门）。

## 验证命令

```bash
uv sync && uv run pytest && uv run ruff check . && uv run mypy
uv run pre-commit run --all-files
openspec validate --changes --strict && openspec validate --specs --strict
# 检索基线回归（需 --all-extras 与本地模型，见 benchmarks/README.md）
```

## 已知坑

- LanceDB 0.38 `list_tables()` 新连接可见性竞态——向量表探测必须用
  `open_table()`（`vector_store.py` 有注释）。
- 基线 v0 生成于 macOS arm64 / Python 3.12.13；跨机 ±0.01 浮动正常，门禁带容差。
- CI 的 `ruff format --check .` 会连 Markdown 代码块一起检查（59a3a73 已清零，
  新增 .md 内代码块注意格式）。
- BYO key：`DEEPSEEK_API_KEY`（默认通道）与 `QWEN_API_KEY`（DashScope qwen-plus）
  均已实测可用。换通道必须同步 `summary_identity=SummaryIdentity(model_id=...)`
  给 `build_graph`，否则 wiki 按设计抛 `GraphArtifactsStaleError`（真实场景已实证）。
- `siku graph` 的 key 校验是惰性的：全部命中缓存时无需 key；`--rebuild` 必须配 key。
  排查日志用 `SIKU_LOG_LEVEL=DEBUG`。
