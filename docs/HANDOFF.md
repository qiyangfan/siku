# HANDOFF — siku 交接文档

> **接驳点，非常驻知识库。** 常驻知识分属四层（按此顺序读，约 5 分钟）：
> 宪法 `openspec/project.md` → 协作规范 `AGENTS.md` → 路线 `docs/ROADMAP.md` →
> 相关决策 `docs/adr/`。本文件每次交接**整体重写**（历史看 `git log`），
> 硬上限 ~60 行：只写“接手者马上需要的状态”，重复常驻文档的内容即为违规。

- **更新时间**：2026-09-17
- **仓库**：`~/siku` → github.com/qiyangfan/siku（私有；SSH 推送，gh keyring 认证）

## 现状

- Phase 0/1 已完成并归档（`78e53d5`、`9e5dbe2`）：脚手架 + 摄取纵切面全绿。
- **Phase 2 检索纵切面已完成**（分支 `feature/phase2-retrieval`，改动全部在工作区，
  **尚未 commit**——等用户确认后提交）。归档 change：`2026-09-17-add-retrieval-vertical-slice`。
  - 新增 `src/siku/retrieve/`（12 模块）：投影解析 → 确定性中文预分词（uni+bigram）→
    SQLite WAL/FTS5 + LanceDB 临时构建-校验-原子切换同步 → BM25+向量 RRF → reranker。
  - CLI：`siku index [--rebuild]` / `siku search` / `siku evaluate-retrieval`，均支持 `--json`。
  - 依赖：`retrieval` extra（sentence-transformers + lancedb）；dev 组含 lancedb 供 CI 用
    fake embedding 打真实向量存储。核心安装零触碰重依赖（isolation 探针测试保障）。
- **baseline v0 已入库**：`benchmarks/retrieval-baseline-v0.json`
  （Recall@5=1.000，MRR@10=0.957；bge-m3 + bge-reranker-v2-m3；27 条 golden set：
  25 PASS + 2 PART、0 FAIL，门禁通过）。
  本地复现见 `benchmarks/README.md`。此后任何检索链路改动必须过此门禁（ADR-0006）。
- 独立评审（review.md，随 change 归档）：2×P1 + 4×P2 全部修复或记档，整改后门禁全绿。

## 下一步（唯一）

**Phase 3 图谱与 wiki**（闸门与边界见 ROADMAP，决策依据 ADR-0003/0005）：抽取后端
（graphify 方法复用）+ 实体/关系/社区落 parquet + 总目条目生成。检索纵切面已备好
稳定 chunk、`source_hash` 溯源与来源锚点，直接复用。先开新分支 `feature/phase3-graph`
并创建 OpenSpec change，再写行为代码。

## 验证命令

```bash
uv sync && uv run pytest && uv run ruff check . && uv run ruff format --check .
uv run mypy && uv run pre-commit run --all-files
openspec validate --changes --strict && openspec validate --specs --strict
# golden set 回归（需要 --all-extras 且本地模型可用，见 benchmarks/README.md）
```

## 已知坑

- LanceDB 0.38 的 `list_tables()` 在新连接上有可见性竞态——向量表探测必须用
  `open_table()`（`vector_store.py` 有注释）。
- baseline v0 生成于 macOS arm64 / Python 3.12.13；换机器分数若有 ±0.01 级浮动属
  正常，门禁比较带 1e-9 容差只判趋势。
