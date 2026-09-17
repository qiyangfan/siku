# 提案：完成 Phase 2 检索纵切面

## Why

Phase 1 已经把源文件稳定投影为带 `source_hash` 与结构锚点的 Markdown 事实层，但当前
系统还不能从 `vault/notes/` 查询内容。下一阶段需要建立可删除、可重建、可回归的本地
检索链路，让检索质量由 golden set 裁决，而不是由单次人工体验裁决。

## What Changes

- 增加从 `vault/notes/` 读取 Markdown 投影并生成检索块的领域模型与索引同步流程。
- 建立自持的 SQLite 元数据/全文 schema，启用 WAL、参数化 SQL 与中文预分词后的 FTS5。
- 建立嵌入式向量索引，支持本地 bge-m3 embedding 与 bge-reranker 重排；重模型只能经
  optional extra 与延迟加载进入，核心安装保持轻量。
- 实现 BM25 与向量候选的混合召回、候选融合、重排和稳定的来源锚点返回。
- 增加 `siku index`、`siku search`、`siku evaluate-retrieval` 三个 CLI 入口，提供人类
  可读输出与机器可读 JSON 输出。
- 入库 golden set v0（至少 24 个覆盖核心场景的问题-期望来源对）及基线分数；检索链路
  变更必须运行回归并报告与基线的差异。

## 受影响决策

- ADR-0003：SQLite + LanceDB 的嵌入式存储边界、SQLite WAL、中文 FTS5 约束。
- ADR-0004：`vault/` Markdown 投影是唯一事实源，检索索引只是可重建派生物。
- ADR-0005：检索模型与存储实现不改变自持 schema；重依赖放入 optional extra。
- ADR-0006：bge-m3 → BM25 混合召回 → reranker，以及 golden set 回归门禁。

## 与项目亮点的关系

图谱与 wiki 仍然是 siku 的核心产品亮点，已在 `docs/ROADMAP.md` 排为 Phase 3，不能被
本 change 删除或降级。本 change 只先完成它们依赖的检索基础：稳定的结构化 chunk、
`source_hash` 溯源、可重建索引和可比较的检索质量基线。Phase 3 将继续从同一事实层和
chunk 元数据生成实体、关系、社区与 wiki，不改变产品定位。

以下能力均为明确延期或后续路线，不是从项目中删除：

| 能力 | 本 change | 后续归属 |
|---|---|---|
| 图谱与 wiki | 不实现 | Phase 3；复用本阶段的事实层、chunk 与来源锚点 |
| HTTP/API 与 WebUI/Tauri UI | 不实现 | Phase 4；先冻结 HTTP 契约，再接入 React/Tauri |
| 问答生成与对话编排 | 不实现 | Phase 4；建立在检索结果之上 |
| 多用户、账号、云端协作 | 不实现 | 不属于当前单机路线；若出现强需求，按 ADR-0002 另开产品线评估 |

## 本 change 不实现（Deferred，不是产品删项）

- 本 change 不实现实体、关系、社区、图谱重建或 wiki 生成；这些仍属于 Phase 3，完成本
  change 后继续排期，不代表从产品范围删除。
- 本 change 不实现 FastAPI/HTTP 契约、React/Tauri UI、对话编排或问答生成；这些仍属于
  Phase 4 及以后，不改变三阶段产品路线。
- 本 change 不实现多用户、账号、云端存储或协作同步；当前产品仍保持 ADR-0002 定义的
  单机本地优先边界，未来强多人需求必须另行评估，不在本 change 内预埋协议。
- 不修改 `vault/` 中的原件或 Markdown 事实层，不处理源文件删除/重命名后的投影回收。
- 不引入云端向量库、独立数据库、账号体系、遥测、同步或多用户并发写入。
- 不实现 OCR、MinerU、Office 在线预览、文档编辑、模型训练或微调。
- 不把真实 LLM/API 调用接入检索；测试只使用可编程 fake provider，embedding 与 reranker
  的本地模型验证由显式命令完成。
