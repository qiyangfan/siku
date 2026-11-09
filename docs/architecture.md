# siku 架构北极星

> 本文档是全项目的决策基准。任何新需求先对照本表校验；偏离表中定稿需要给出比表中理由更强的理由，并更新本文档。

定稿时间：2026-09-17。决策准则：资深架构师视角，优先简洁优雅、代码质量、长期维护与用户体验；不受现状束缚，输出最优完整方案。

本文是选型快照总表；每项决策的完整论证、被否选项与复核信号见 `docs/adr/`（ADR-0001~0014），两者冲突时以 ADR 为准。不可协商红线见 `openspec/project.md`。

## 0. 产品定位

把所有文档丢进去，经自动知识图谱 + LLM wiki + RAG，用自然语言检索。

- 市场裁决：纯向量 RAG 知识库是红海（AnythingLLM/RAGFlow/Open WebUI），不碰；**空白点 = "自动图谱 + wiki 生成 + 本地优先"的组合，无消费级成品**。
- Obsidian 只是 Markdown 编辑器（图谱为链接关系，无语义），是格式兼容对象，不是竞品。
- 不做文档编辑器、不做 SaaS 多租户、不做 Obsidian 克隆。

## 1. 总体形态

**本地优先；终态 = Tauri 桌面壳；开发期 = localhost WebUI。**

| 阶段 | 形态 | 受众 | 成本 |
|---|---|---|---|
| 一（当前） | `uv tool install` + localhost WebUI + CLI | 开发者/早期用户 | 零 |
| 二 | Tauri 壳（不签名），GitHub Releases + Homebrew | 尝鲜用户 | ≈0 |
| 三 | 签名 + 自动更新 | 全量用户 | Apple $99/年 + Azure Trusted Signing ~$10/月 |

隐私叙事：本地应用 ≠ 全离线。抽取/问答调 LLM API 时文本片段瞬时出户，但**无服务器持久化语料、无账号、无锁定**；配套 BYO key + Ollama 全离线降级通道 + 隐私说明。

## 2. 语言与进程边界

- **内核 Python 3.12+**（uv 管理，FastAPI）；**UI TypeScript/React + Mantine Core 9.x**，图视图使用 Sigma.js + graphology。
- 否决 Java/Go/纯 Rust 做内核：图谱/RAG 生态（GraphRAG、LightRAG、sentence-transformers、Docling）全在 Python，重写无收益。
- **红线：UI ↔ 内核只经 localhost HTTP API**，业务逻辑禁入前端。
- AI 客户端接入走 MCP（stdio）：`siku mcp` 与 CLI 同级，是内核的本地客户端面而非 UI，直连内核、不依赖 serve（ADR-0014）。

## 3. 数据主权（最重要的一条）

**自持 schema**：chunk / entity / edge / community 的持久化格式由本项目定义（SQLite + parquet）。GraphRAG、LightRAG、graphify 等一律实现统一 Extractor 接口，作为**可插拔抽取后端**接入——研究引擎版本间 API 与存储漂移剧烈，产品数据层绝不绑定。

**红线：抽取管线幂等**。语料是唯一事实源；图谱/wiki/索引皆为派生物，按 `source_hash` 单文件重抽、支持全量重建。做不到幂等的产品一年后会被自己的旧图谱锁死。

## 4. 存储层

| 层 | 选型 | 否决项 |
|---|---|---|
| 元数据/全文 | SQLite（WAL + JSON1 + FTS5 中文分词插件） | Postgres 等 server 形态（违背零运维） |
| 向量 | LanceDB embedded | Qdrant/Milvus server；sqlite-vec（百万级上限） |
| 图谱 | 内存图（NetworkX 起步，10⁵ 边级换 igraph）+ parquet 落盘 | Neo4j（JVM server）；Kuzu（2025 已归档） |
| 正文 | 磁盘 Markdown，Obsidian vault 兼容 | 正文入库（用户数据锁定） |
| NoSQL | **不引入**，SQLite JSON1 + parquet 覆盖 | MongoDB/Redis（本地单机上的架构倒挂） |

中文大坑：FTS5 默认分词器对中文无效，必须配 `simple` 分词插件或 jieba 预分词。

## 5. 万能摄取

**格式放开，存储不变**：一切格式 → Markdown 投影（唯一事实层），原件拷贝进 `vault/attachments/` 溯源。

```
vault/
  attachments/   ← 原件（单文件夹可备份可迁移，默认拷贝不外链）
  notes/         ← Markdown 投影（frontmatter 记 source_hash / 页码锚点）
```

| 格式 | 方案 | 协议 | 要点 |
|---|---|---|---|
| PDF | Docling（主力）+ MinerU（中文/扫描插件） | MIT / AGPL-3.0 | 唯一真难题；MinerU 子进程隔离，不做 pip 依赖 |
| Word | pandoc（外部二进制） | GPL-2+（无传染） | 标题/表格/脚注/图片全收 |
| PPT | python-pptx | MIT | 按 slide 切块 |
| Excel | openpyxl | MIT | sheet → Markdown 表格块；全量查询走 DuckDB，不进检索层 |
| EPUB/HTML | pandoc / trafilatura | — | 零边际成本 |

工程红线：① 切块必须结构感知（章节/slide/sheet），禁止 token 硬切；② 溯源锚点抽取时写入 frontmatter，引用可跳回原文；③ hash 变更单文件重抽。

不做：Office 在线预览/编辑（"打开原文"交系统应用）。

## 6. 检索质量层

bge-m3 向量化 → BM25 混合召回 → bge-reranker 重排 → **golden set 回归评测**（几十个"问题+应命中文档"标注对，改检索参数必跑）。无回归集的检索调优是玄学。

增强通道：实体 join 检索（ADR-0015）——查询时实体共现 join 取桥接证据，纯确定性零模型调用，只读图谱 parquet 与检索索引两份派生物；消费面先行 MCP 只读工具，主链路四段与 golden set 门禁不变，多跳评测集另立。

## 7. 模型层

- embedding：本地（bge-m3 / Ollama）
- 图谱抽取：API 强模型，BYO key（graphify + DeepSeek 已端到端验证）
- 问答 LLM：可配置，本地/API 双通道

## 8. 命名

**siku（四库）**：《四库全书》= 历史上最大规模的"汇总文献 → 自动编目（总目提要）→ 结构化检索"工程，与产品同构。实测 pypi / npm / Homebrew 全空闲（summa、mycelium、rhizome、engram、trove 均被占，已淘汰）。
