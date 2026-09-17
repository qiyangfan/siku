# HANDOFF — siku 交接文档

> **接驳点，非常驻知识库。** 常驻知识分属四层（按此顺序读，约 5 分钟）：
> 宪法 `openspec/project.md` → 协作规范 `AGENTS.md` → 路线 `docs/ROADMAP.md` →
> 相关决策 `docs/adr/`。本文件每次交接**整体重写**（历史看 `git log`），
> 硬上限 ~60 行：只写“接手者马上需要的状态”，重复常驻文档的内容即为违规。

- **更新时间**：2026-09-18
- **仓库**：`~/siku` → github.com/qiyangfan/siku（私有；SSH 推送，gh keyring 认证）

## 现状

- Phase 0/1/2 全部完成：检索纵切面已**合入 main 并推送**（main @ `21b0d77`，
  fast-forward 自 `feature/phase2-retrieval`）。baseline v0 与 golden set 在
  `benchmarks/`，检索链路任何改动必须过基线门禁（ADR-0006）。
- Phase 3 已启动：分支 `feature/phase3-graph`，change
  `add-graph-wiki-vertical-slice` 已 propose 全件并通过 strict 校验（proposal/
  design/tasks/specs/graph-wiki）——**尚未 apply，未写任何行为代码**。
- 设计要点（详见 change design.md）：抽取缓存键 = sha256(chunk_hash+抽取器/模型+
  prompt 版本)，幂等闸门 = 同语料二次构建零 LLM 调用 + 删本体重建 diff 为空；
  图谱本体落 parquet、缓存落 SQLite、内存图 NetworkX（固定 seed）；LLM 走
  openai 兼容通道 BYO key（`SIKU_LLM_API_KEY`），CI 只用 fake provider 五剧本。

## 下一步（唯一）

在 `feature/phase3-graph` 上 **apply** `add-graph-wiki-vertical-slice/tasks.md`
（15 项，测试先行，粒度 ≤2h）：领域模型/协议 → LLM fake 五剧本 → 抽取解析 →
缓存 → 合并与落盘 → 社区发现 → wiki 渲染 → CLI → 幂等闸门 → 依赖纪律 →
BYO key 真实冒烟 → 全量门禁 + review.md + 归档同步。

## 验证命令

```bash
uv sync && uv run pytest && uv run ruff check . && uv run ruff format --check .
uv run mypy && uv run pre-commit run --all-files
openspec validate --changes --strict && openspec validate --specs --strict
# 检索基线回归（需 --all-extras 与本地模型，见 benchmarks/README.md）
```

## 已知坑

- LanceDB 0.38 的 `list_tables()` 在新连接上有可见性竞态——向量表探测必须用
  `open_table()`（`vector_store.py` 有注释）。
- 基线 v0 生成于 macOS arm64 / Python 3.12.13；跨机器分数 ±0.01 级浮动属正常，
  门禁比较带 1e-9 容差只判趋势。
- CLI 日志默认 WARNING（stderr 即用户面），排查用 `SIKU_LOG_LEVEL=DEBUG`；非法
  取值自动回退 WARNING。
