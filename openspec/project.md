# 项目宪法（siku）

siku（四库）——本地优先的个人知识库：丢入全部文档（PDF/Word/PPT/Excel/EPUB/HTML/Markdown），
自动摄取为 Markdown 事实层，构建知识图谱与 LLM wiki，通过自然语言问答检索。
选型总表见 `docs/architecture.md`（北极星）；每项决策的完整论证见 `docs/adr/`（ADR-0001~0008）。
本文是代码评审的基线；与根 `AGENTS.md` 铁律冲突时以 AGENTS.md 为准。

## 不可协商的红线

1. **本地优先**（ADR-0002）：语料与索引永不离用户磁盘；远程仅允许用户自配 key 的 LLM API
   瞬时调用与用户显式开启的模型下载。禁止引入账号体系、遥测上传、云端存储。这是"丢进
   全部个人文档"这一场景唯一说得通的信任方案——服务器持久化语料 = 产品不成立。
2. **UI ↔ 内核进程边界**（ADR-0002）：UI 只经 localhost HTTP API 访问内核，
   业务逻辑禁止进入前端或 Tauri 壳。这不是洁癖：三阶段发布路线（localhost WebUI →
   Tauri 无签名 → 签名桌面）成立的前提就是内核对 UI 形态零假设。
3. **语料唯一事实源**（ADR-0004）：`vault/`（notes/ Markdown 投影 + attachments/ 原件）是
   唯一事实层；图谱、wiki、索引、统计皆为派生物，必须支持按 `source_hash` 单文件重抽与
   全量重建。任何"顺手修改用户语料"的代码路径视为缺陷。做不到幂等重跑的产品，一年后
   会被自己的旧图谱锁死。
4. **数据主权**（ADR-0005）：chunk/entity/edge/community 的持久化 schema 由本项目定义；
   GraphRAG/LightRAG/graphify 等一律经 Extractor 接口作可插拔后端。研究引擎版本间
   API 与存储格式漂移剧烈，产品数据层绑定引擎 = 定期被迫重写。
5. **检索质量回归**（ADR-0006）：golden set 是检索行为的可执行规格。改动检索链路
   （切块/embedding/召回/重排/参数）必须过回归，未跑不得合入——无回归集的检索调优是玄学。
6. **核心安装轻量**（ADR-0005）：torch 系重依赖一律放 `[project.optional-dependencies]`；
   核心依赖保持秒级安装。抽取引擎的重量不允许转嫁给不用该引擎的用户。

## 工程口径

### 存储与 SQL

- 三件套：SQLite（WAL + JSON1 + FTS5）+ LanceDB + parquet；禁止 server 形态数据库与
  独立 NoSQL（ADR-0003）。
- SQLite 连接必须 `PRAGMA journal_mode=WAL`；SQL 一律参数化占位（`?`），禁止字符串拼接。
- FTS5 默认分词器对中文无效：中文全文检索必须经分词插件或预分词，禁止裸 FTS5 上中文。
- `source_hash` = 原件字节的 SHA-256，写入投影 frontmatter 与 chunk 元数据；
  hash 不变不重抽，hash 变更只重抽该文件。

### 代码规范

- Python 3.12+，src 布局；公开 API 全类型注解（`py.typed` 已启用）；ruff 是唯一
  lint/format 权威，`noqa` 必须注明原因。
- 注释只写代码说不出的东西：为什么这么选、边界与陷阱、与上游协议的差异来源；禁止逐行复述。
- 禁止 `print` 调试输出（`typer.echo` 除外）；包名按领域切（`ingest`/`retrieve`/`graph`/
  `wiki`/`serve`），禁止 `utils`/`common` 垃圾抽屉名。
- 抽取引擎落位 `src/siku/extractors/`，每引擎一个模块，实现统一 `Extractor` 协议；
  AGPL 引擎（MinerU）只准子进程隔离接入，禁止 pip 依赖。

### CLI 与错误处理

- CLI 命令 = 动词原形子命令：`siku ingest` / `siku serve` / `siku version`；管线操作
  （摄取/重建索引/生成 wiki）必须是一等 CLI 命令，GUI 不是管线活的前置条件。
- 错误双轨（借鉴 muniu/kongming 范式）：CLI 与 HTTP 响应只给归一化的用户可读 message
  （简体中文）；技术细节（异常链、栈）进日志 `error_detail` 字段，不漏到用户面。

### 日志

- 文本英文，结构化字段 snake_case；摄取与问答链路每请求必带 `request_id`。
- 字段命名表：`request_id / doc_id / source_hash / extractor / chunk_count /
  embed_model / retrieve_top_k / rerank_top_k / latency_total_ms / error_class`。
  新增字段先进本表评审再使用。

### 测试范式

- 表驱动为主：`test_xxx_场景` 命名；断言失败信息必须能定位到场景。
- **假上游是核心测试设施**：LLM 调用、embedding 调用在测试中只打可编程 fake
  （正常/超长/空返回/限流/断连五剧本），CI 永不打真实 API——成本与可重复性双重要求。
- golden 文件入库管理：golden set 标注对与抽取期望产物均为 fixture，变更必须连同理由
  一起提交；golden set 回归是检索链路的合入门禁（ADR-0006）。

### Git 与文档

- commit message 简体中文（subject + body）；未经用户明确指示禁止 commit/push。
- 文档、注释中文；日志英文；标识符英文；CLI 用户文案中文。

## 治理三层（速查）

| 层 | 位置 | 回答 | 变更方式 |
|---|---|---|---|
| 决策 | `docs/adr/` | 为什么这么做 | 新增 ADR；旧的不删，只改状态 |
| 宪法 | `openspec/project.md` | 不可协商红线 | 改条款须同步对应 ADR |
| 契约 | `openspec/specs/` | 系统应如何行为 | change 的 deltas 归档时 sync 而入 |
| 提案 | `openspec/changes/` | 这一步做什么/不做什么 | propose → apply → review → archive |
