# HANDOFF — siku 交接文档

> **接驳点，非常驻知识库。** 常驻知识分属四层：宪法 `openspec/project.md`、协作规范
> `AGENTS.md`、路线 `docs/ROADMAP.md`、相关决策 `docs/adr/`。本文件每次交接整体重写，
> 只写接手者马上需要的状态。

- **更新时间**：2026-09-19（第十一次，读取面语义收敛 + 四项质量修复已入库推送）
- **仓库**：`~/siku` → github.com/qiyangfan/siku（私有；SSH 推送，gh keyring 认证）

## 现状

- **读取面语义收敛 + 四项质量修复已入库（fix(api) b5d3c59，已推送）**，内容两块：
  1. **wiki 读失败口径收敛**（归档件 add-browse-graph-wiki-views design.md 记账项）：
     新增 `WikiEntryReadError`（read_text 与 mtime stat 双折叠），wiki 单条读失败
     返回 422 `wiki_entry_parse_error`，与 notes 422 口径对齐（新增稳定错误码 1 个）。
  2. **读取面四项质量修复**：①清单 fail-fast → 单条降级（notes 投影损坏跳过留痕、
     wiki 单条损坏跳过留痕，目录级 OSError 分别降级空清单/404，读取面数据性问题
     不再落 500；检索索引侧 `scan_note_frontmatters` 保持 fail-fast 不动）；
     ②409/422 边界成文（整库级损坏 409、单条目级损坏 422，规则见
     `reading.py` 模块 docstring）；③新增 `AttachmentDigestCache`（library 附件
     SHA-256 的 stat 快路径，进程内不落盘，`GET /api/library` 不再每请求全量读盘）；
     ④新增 `messages.map_read_error`（8 个只读端点错误码单一成文点，端点内联
     字面量清零；GraphArtifactsMissingError 读 404/写 409 分野显式成文）。
- 本笔验证：pytest **586**、ruff check/format、mypy 全绿；两轮独立子代理 review
  均「无阻断缺陷」，改进项全部采纳。主 specs 与 OpenAPI 快照未动（无端点/模型
  结构变化，无被冻结行为反转）。工作树干净，main 已与远端同步。
- **遗留 tag 已清理**：`v0.1.0`（指向 main 上 1c07b8b）已删本地与远端；Release
  无限期禁用不变。
- **`add-browse-graph-wiki-views` 已归档提交**；桌面链路「配模型 → 进资料 →
  看知识」闭环，ROADMAP Phase 5++ 全部勾稽。
- **下一阶段无明确任务，未预写 openspec 骨架**：Phase 6 签名与自动更新等发布解禁
  决策；触发器台账全等外部环境。开新 change 前先到 ROADMAP 对齐排序。

## 已知坑

- **读取面错误语义边界**（`reading.py` docstring 为权威）：整库级损坏 → 409
  `graph_store_corrupt`；单条目级损坏 → 422；清单面单条损坏（含权限等 OSError）
  跳过留痕，wiki 单条按编号寻址 422、notes 损坏投影身份不可知按 404。全部读
  错误码只在 `messages.map_read_error` 成文，端点禁止内联字面量——新只读端点照此。
- **`AttachmentDigestCache` 边界**：stat 锚点（size+mtime_ns）仅供呈现层，误判
  由摄取按真实 source_hash 自愈；**不得复用于跳过重抽等事实层决策**（届时须换
  size+mtime+inode 或内容抽样锚点），不得跨 vault 共享实例。
- **spec「领域错误归一」三类状态码（409/422/503）不含读面 404**：note/wiki/graph
  的资源未生成类 404 是上批归档变更引入的既成事实；未来开 change 时可顺带把
  「未生成/不存在 → 404」补进规格枚举。
- **读取面实现口径**：notes 单篇按 source_id 现扫 frontmatter 匹配、图谱每请求
  现读 parquet、wiki 时效取条目文件 mtime、孤立实体度数按 0 兜底；图谱/wiki
  读取不做进程内缓存，量级复核归 ADR-0003。
- **画布**：`GraphCanvas.tsx` 挂载即建 Sigma 实例，数据变更整体重建图内容；jsdom
  无 WebGL，单测以 vi.mock 替身呈现、真实交互在归档 review.md 冒烟段记账。
  社区着色 = community_id 对 12 色调色板取模。
- **Markdown 安全渲染唯一入口** `ui/src/markdown.ts`（marked→DOMPurify）+ 只读
  链接守卫；禁止裸 `dangerouslySetInnerHTML`。
- 前端各视图异步操作用**独立请求序号 ref** 防竞态——跨操作不共用（评审循环教训）。
- 资料库任务/serve 供给装配/设置合并语义/`mypy` 不带路径参数/pytest 勿在 ui/ 下跑
  等沿袭既有归档件，不赘述。
- 手工冒烟缺真实模型时：openai 兼容 mock（/embeddings + /chat/completions）即可
  跑通全链路，做法见归档 review.md 冒烟段。

## 触发型（不主动做，全在 ROADMAP 台账有账）

Phase 6 签名与自动更新（等发布解禁决策）；Windows/Linux 实机冒烟（等发布解禁，
清单见 docs/desktop.md）；双通道基线补录（等 Ollama/云端 key 环境）；设置中心/
资料库/三知识视图 Tauri 壳内真实端点界面级冒烟（等真实 BYOK 环境）。
