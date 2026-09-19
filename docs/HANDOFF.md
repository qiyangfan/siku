# HANDOFF — siku 交接文档

> **接驳点，非常驻知识库。** 常驻知识分属四层：宪法 `openspec/project.md`、协作规范
> `AGENTS.md`、路线 `docs/ROADMAP.md`、相关决策 `docs/adr/`。本文件每次交接整体重写，
> 只写接手者马上需要的状态。

- **更新时间**：2026-09-19（第十次，add-browse-graph-wiki-views 已归档提交，工作树干净）
- **仓库**：`~/siku` → github.com/qiyangfan/siku（私有；SSH 推送，gh keyring 认证）

## 现状

- **`add-browse-graph-wiki-views` 已归档提交**（`changes/archive/2026-09-19-add-browse-graph-wiki-views/`）：
  8 个只读 GET 端点（notes 清单/单篇、graph stats/overview/search/neighbors、
  wiki 清单/单条）+ 服务端有界子图（overview≤500/search≤100/neighbors≤200，超限 422、
  邻域候选按层序优先/层内择优裁剪并带 `truncated`+total）+ 浏览/图谱/wiki 三视图
  （Sigma.js 画布、marked+DOMPurify 防注入渲染与只读链接守卫、实体→问答预填联动）；
  http-api +3 / web-ui +1 增量已入主 specs。批次按模块分四笔入库：
  feat(api) abf01be / feat(ui) 902ad95 / chore(openspec) 08ab455 / docs（本笔），
  工作树干净、未推送远端。
- **桌面上手链路闭环**：配模型（设置中心）→ 进资料（资料库）→ 看知识（本批）。
  ROADMAP Phase 5++ 全部勾稽完毕；openspec 无活跃 change。
- **下一阶段无明确任务，未预写 openspec 骨架**：Phase 6 签名与自动更新等发布解禁
  决策；触发器台账全部等外部环境。开新 change 前先到 ROADMAP 对齐排序。
- 门禁基线（归档 + 评审循环收敛后复验）：pytest **577**、ruff check/format、mypy、
  pre-commit、openspec strict（specs 7/7，无活跃 change）、npm lint/test（43）/build
  全绿。归档件 review.md 含评审循环记录（三域初审 25 findings → 16+4 项修复、
  4 项虚构剔除，第 2 轮对抗复审再修 4 项含 P1 孤立实体 500，第 3 轮收敛）。
- Release 无限期禁用不变，`v0.1.0` tag 遗留未删。

## 已知坑

- **读取面实现口径**：`siku/api/reading.py` 纯派生只读——notes 单篇按 source_id
  现扫 frontmatter 匹配（不依赖文件名约定）、图谱每请求现读 parquet、wiki 时效取
  条目文件 mtime（渲染器确定性无时间戳）、孤立实体度数按 0 兜底。全部不做进程内
  缓存；量级复核归 ADR-0003。
- **画布**：`GraphCanvas.tsx` 挂载即建 Sigma 实例，数据变更整体重建图内容（有界
  ≤数百节点）；jsdom 无 WebGL，单测以 vi.mock 替身呈现画布、画布真实交互在归档件
  review.md 冒烟段记账。社区着色 = community_id 对 12 色调色板取模。
- **Markdown 安全渲染唯一入口** `ui/src/markdown.ts`（marked→DOMPurify）+ 只读
  链接守卫 `handleMarkdownClick`；新视图渲染用户内容必须走它，禁止裸
  `dangerouslySetInnerHTML`。
- 前端各视图异步操作用**独立请求序号 ref** 防竞态——跨操作不共用（共享会让被否决
  方 loading 旗标永久卡死，评审循环实测教训）。
- 资料库任务/serve 供给装配/设置合并语义/`mypy` 不带路径参数/pytest 勿在 ui/ 下跑
  等沿袭既有归档件，不赘述。
- 手工冒烟缺真实模型时：openai 兼容 mock（/embeddings + /chat/completions）即可
  跑通全链路，做法见本 change 归档 review.md 冒烟段（含只读边界 mtime 实证）。

## 触发型（不主动做，全在 ROADMAP 台账有账）

Phase 6 签名与自动更新（等发布解禁决策）；Windows/Linux 实机冒烟（等发布解禁，
清单见 docs/desktop.md）；双通道基线补录（等 Ollama/云端 key 环境）；设置中心/
资料库/三知识视图 Tauri 壳内真实端点界面级冒烟（等真实 BYOK 环境；serve 级全链路
已在各归档 review.md 记账）。
