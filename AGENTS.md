# AGENTS.md — siku 开发协作规范

本文件面向在本仓库工作的 AI 编码代理与人类协作者。任何改动前先读一遍。

## 项目是什么

siku（四库）——本地优先的个人知识库：丢入全部文档（PDF/Word/PPT/Excel/EPUB/HTML/Markdown），自动摄取为 Markdown 事实层，构建知识图谱与 LLM wiki，通过自然语言问答检索。当前处于脚手架阶段。

架构北极星见 [docs/architecture.md](docs/architecture.md)。任何设计决策先对照该文档；要偏离表中定稿，必须给出比文档中理由更强的理由。

## 治理三层

| 层 | 位置 | 回答 | 变更方式 |
|---|---|---|---|
| 决策 | `docs/adr/`（ADR-0001~0008） | 为什么这么做 | 新增 ADR；旧的不删，只改状态 |
| 宪法 | `openspec/project.md` | 不可协商红线 6 条 + 工程口径 | 改条款须同步对应 ADR |
| 契约 | `openspec/specs/` | 系统应如何行为 | change 的 deltas 归档时 sync 而入 |
| 提案 | `openspec/changes/` | 这一步做什么/不做什么 | propose → apply → review → archive |

流程细则见 [openspec/AGENTS.md](openspec/AGENTS.md)：无 change 不写功能代码；
proposal 必须含 Non-goals 并引用受影响 ADR；任务粒度 ≤ 2 小时。
排序与遗忘防线见 [docs/ROADMAP.md](docs/ROADMAP.md)：**开 change 前先对齐排序，
归档 change 后回写勾稽**；远期项进 Backlog 而非预写 openspec 骨架。
交接状态见 `docs/HANDOFF.md`（仅本地维护，**不入库**；内容含真实环境细节，公开仓库不携带此文件）：每次交接**整体重写**（禁止追加），
硬上限 ~60 行，只写接手者即时需要的状态，常驻知识一律指向四层文档。

## 架构红线（违反即打回）

1. **UI ↔ 内核只经 localhost HTTP API 通信**，业务逻辑禁止进入前端或未来的 Tauri 壳。这是三阶段发布路线成立的前提。
2. **抽取管线幂等**：语料文件（含 attachments/ 原件）是唯一事实源，图谱/wiki/索引皆为派生物，必须支持按 `source_hash` 单文件重抽与全量重建。
3. **数据主权**：自持 schema（SQLite + LanceDB + parquet 三件套），GraphRAG/LightRAG 等引擎一律通过统一的 Extractor 接口作可插拔后端，禁止绑定任何引擎的内部存储格式。
4. **核心安装保持轻量**：torch 系重依赖（Docling 等）必须放 `[project.optional-dependencies]`，不得进核心 dependencies。

## 常用命令

```bash
uv sync                    # 安装依赖（含 dev 组）
uv run pytest              # 测试
uv run ruff check .        # Lint
uv run ruff format .       # 格式化
uv run pre-commit run --all-files   # 全量 hooks
```

## 代码规范

- Python 3.12+，src 布局；所有公开函数/方法必须有类型注解（包级 `py.typed` 已启用）
- **注释、docstring、技术文档用简体中文**；**日志文本用英文**（面向运维）；标识符用英文
- ruff 是唯一的 lint/format 权威；`noqa` 必须注明原因
- 业务报错信息（面向用户抛出的异常 message）用英文
- 新功能必须带 pytest 测试；修 bug 先写复现测试再修
- SQL 一律参数化（`?` 占位），禁止字符串拼接；SQLite 连接启用 WAL 模式
- 禁止 `print` 输出调试信息（CLI 的 `typer.echo` 除外），用 `logging`

## 依赖纪律

- 新增依赖前先确认能否用标准库或已有依赖实现
- 数据存储只允许 SQLite / LanceDB / parquet 三件套，禁止引入 server 形态数据库（Neo4j/Postgres/Redis 等）
- 抽取引擎只准经 Extractor 接口接入（子进程隔离的 AGPL 引擎如 MinerU 除外），禁止 import 引擎内部模块

## Git 规范

- commit message 用中文（subject + body），格式参考：`feat(ingest): 新增 PDF 抽取后端`
- **未经用户明确指示，禁止执行 git commit / git push**
- 单分支开发：直接在 main 上开发，不建 feature 分支
