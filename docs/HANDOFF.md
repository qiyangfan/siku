# HANDOFF — siku 交接文档

> **接驳点，非常驻知识库。** 常驻知识分属四层（按此顺序读，约 5 分钟）：
> 宪法 `openspec/project.md` → 协作规范 `AGENTS.md` → 路线 `docs/ROADMAP.md` →
> 相关决策 `docs/adr/`。本文件每次交接**整体重写**（历史看 `git log`），
> 硬上限 ~60 行：只写"接手者马上需要的状态"，重复常驻文档的内容即为违规。

- **更新时间**：2026-09-18
- **仓库**：`~/siku` → github.com/qiyangfan/siku（私有；SSH 推送，gh keyring 认证）

## 现状

- **Phase 0/1/2/3 全部完成并合入 main**。Phase 3（图谱与 wiki 纵切面）归档为
  `2026-09-18-add-graph-wiki-vertical-slice`，graph-wiki spec 已同步（6 Requirement），
  ROADMAP 已勾稽。全仓 369 测试绿，mypy/ruff/pre-commit/openspec strict 全过。
- 交付：`src/siku/graph/`（协议抽取/五剧本错误/SQLite WAL 缓存/合并/社区/parquet/
  体检）+ `src/siku/wiki/`（摘要/确定性渲染/编排）+ CLI `siku graph`/`siku wiki`。
  幂等闸门与种子敏感确定性闸门有自动化证据（`tests/test_graph_idempotence.py`、
  `test_graph_community.py`）；五轮独立评审循环收敛 CLEAN（记录在归档 change 的
  review.md）；真实冒烟已过（DeepSeek 通道 10 次调用，质量复核合格）。
- 依赖纪律：httpx/networkx/pyarrow 已进核心依赖（轻依赖，红线 #4 不受影响）；
  pyarrow 相应移出隔离测试拦截名单。

## 下一步（唯一）

Phase 4 WebUI 最小集：先对齐 ROADMAP/ADR-0002 开 change 冻结 FastAPI 三端点契约
（摄取/检索/图谱），UI 侧零业务逻辑（红线 #1；UI 评审走 ui-quality-gate 闸门）。
图谱检索通道（图遍历召回）属按需叠加，不在 Phase 4 默认范围。

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
- `siku graph` 的 key 校验是惰性的：全部命中缓存时无需 key；`--rebuild` 必须配 key。
  排查日志用 `SIKU_LOG_LEVEL=DEBUG`。
- BYO key：`DEEPSEEK_API_KEY`（默认通道）与 `QWEN_API_KEY`（DashScope 兼容端点，
  qwen-plus）均已实测可用；换通道必须同步传 `summary_identity=SummaryIdentity(
  model_id=...)` 给 `build_graph`，否则 wiki 阶段会按设计拒绝（GraphArtifactsStaleError）。
  冒烟脚本范式见归档 change review.md。
