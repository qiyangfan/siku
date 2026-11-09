# 评审记录：add-entity-join-retrieval

> 状态：实施完成 + 代码审查迭代循环已过一轮（两缺陷修复并复验）。**已归档
> （2026-11-09，归档目录 `2026-11-09-add-entity-join-retrieval`）**：owner 指示随
> 当轮收口直接归档，独立评审轮未另行执行，以代码审查循环记录与全量门禁复验
> （887 passed + e2e 2 passed + ruff 双清 + `--specs --strict` 10/10）为准。

## 代码审查循环（2026-11-09，范围 = 本会话全部未提交变更）

已证实并修复（各带回归测试，修复后全量复验）：

1. **错误分型穿透**（`mcp/server.py` tool_entity_evidence）：`InvalidQueryError ⊂
   RetrievalError`，原 except 只捕 Graph/Index 错误——空白查询（过得了 schema
   `min_length=1`）被 `_call` 掩盖成 `internal_error`，与 `search` 工具的
   `invalid_query` 口径漂移。修法：except 收敛为 `(GraphArtifactsMissingError,
   GraphStoreCorruptError, RetrievalError)`；新增回归
   `test_blank_query_maps_to_invalid_query`。
2. **rerank_score 契约不一致**（`retrieve/entity_join.py` plan_join）：契约规定
   rerank_score 是「最终排序第一关键字」，原打分种子=count(1–8)、桥接=count(1–50)，
   按 分数降序重排的消费端会逆转「种子在前」既定序。修法：种子分加层级偏移
   （count + max(桥接count)+1），跨类恒序、类内保序；新增不变量断言。

复验证据：本件聚焦 **52 passed**；全量 **888 passed, 1 failed**（唯一失败为下述既有
flaky，与修复前一致）；ruff 本件五文件 All checks passed；mcp-server delta SHALL 段
376/500 字符；`openspec validate --changes --strict` 2 passed、`--specs --strict` 9/9。

非问题/约定（不改）：`tool_entity_evidence`/`tool_graph_search` 的 `vault` 形参未使用
——与既有图工具保持统一签名的既有约定。

## 实施验证证据（2026-11-09，本机 main）

命令口径：`env -u DASHSCOPE_API_KEY uv run python -m pytest -o addopts=""`（HANDOFF 记载）。

- 全量 pytest：**887 passed, 1 failed**（2:48）。唯一失败为
  `test_sync_removal.py::test_two_process_mutex_via_subprocess`——**既有 flaky，非本件
  引入**（归因见下节）。基线核对：862（HANDOFF 2026-10-18）+ 本件新增 25 只
  （test_entity_join 16 + test_entity_join_multihop 3 + test_mcp_server 4 工具层 +
  协议层断言扩展）+ 并行在途 change 的 2 只 e2e（被当次 `-o addopts=""` 带入，通过）。
- 本件三文件聚焦：`pytest tests/test_entity_join.py tests/test_entity_join_multihop.py
  tests/test_mcp_server.py` → **51 passed**。
- ruff：本件五文件 `ruff check` **All checks passed**；`ruff format` 已套用。
  全树仅余 `tests/e2e/conftest.py` 一处 E501（并行在途文件，非本件范围）。
- `openspec validate --changes --strict`：**2 passed, 0 failed**。
- 既有链路零触碰：`git status` 中 `src/siku/retrieve/{store,service,indexer}.py`、
  golden set、图谱构建路径均无改动；本件 src 改动仅 `retrieve/entity_join.py`（新增）
  与 `mcp/server.py`（工具接线与 imports）。

## 多跳评测对照数字（任务 3.2，`--log-cli-level=INFO` 实录）

中文合成语料（16 对标注：桥接 8 / 共现 5 / 歧义 3 + 4 篇噪声）：

| 场景 | 对数 | join Recall@10 | 纯混合召回 Recall@10 |
|---|---|---|---|
| 跨文档第三实体桥接（桥接块不含种子名） | 8 | **1.00（8/8）** | **0.12（1/8）** |
| 单文档共现 + 同名歧义多上下文 | 8 | 1.00（8/8） | 1.00（8/8） |

结论如实记录：桥接场景 join 通道 8/8 全命中且逐对带桥接实体溯源，纯混合召回仅 1/8
——SAG 论文判断（确定性 join 补桥接盲区）在中文合成语料上成立；共现/歧义场景本就在
混合召回能力圈内，join 通道持平不劣化。通道正确性门禁（join 桥接逐对命中）已入
pytest 断言；混合召回对照不设阈值、仅记录（ADR-0015 风险条款）。

## 既有 flaky 归因（非本件缺陷，不动）

`test_two_process_mutex_via_subprocess`：holder 子进程持锁 3s，CLI 写锁等待窗
`_CLI_WRITE_LOCK_TIMEOUT_SECS = 2.0`（`cli.py:271`），断言依赖 CLI 子进程冷启动耗时
把 3s 窗口耗到 2s 等待窗之外——即 busy 分支只有在启动延迟 > ~1s 时才被走到。本机
当前启动更快 → holder 释放后 CLI 合法获锁 → `sync_index` 对测试 setup（仅建 `vault/`
根，无 `notes/`）报"未找到 vault/notes"。隔离复跑两次均红；`tests/test_sync_removal.py`、
`src/siku/cli.py`、`src/siku/sync/` 在工作区与 HEAD 零 diff（含并行会话改动），非任何
在途改动引入。修复方向（后续独立处理）：测试 setup 显式建 `vault/notes/` 或加长
holder 持锁时间，使断言不依赖启动时序。

## 遗留与边界

- 独立评审（P0/P1/P2 分级复核）待做；归档随独立评审后执行，届时同步主规格
  （`entity-join` Purpose 入档、`mcp-server` Purpose 更新为七个只读工具）。
- 升级路径（ADR-0015 复核信号）：LLM query 实体抽取、LLM 证据链重排、`/api/ask`
  opt-in 集成（须过 golden set 门禁另开 change）——本轮均未做，属 Non-goals。
