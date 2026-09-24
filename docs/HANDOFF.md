# HANDOFF — siku 交接文档

> **接驳点，非常驻知识库。** 常驻知识分属四层：宪法 `openspec/project.md`、协作规范
> `AGENTS.md`、路线 `docs/ROADMAP.md`、相关决策 `docs/adr/`。本文件每次交接整体重写，
> 只写接手者马上需要的状态。

- **更新时间**：2026-09-24（第十五次，三层积压改动已按 change 分笔提交至
  `edce9f6` 并推送 origin/main）
- **仓库**：`~/siku` → github.com/qiyangfan/siku（私有；SSH 推送，gh keyring 认证）

## 现状

- 本批三笔提交（owner 指示「归档、写好 handoff、提交所有代码」后落地）：
  - **`160b08e` feat(api): 问答就绪门控**（add-ask-readiness-gate 归档）：内核
    `ask_readiness`、settings 响应带 `{ready, missing[]}`、问答未配置置灰 + 引导
    卡片 + fail-open、OpenAPI 快照刷新。
  - **`cee4caa` feat(ui): 设置中心 key_mode 分段凭证**（并行任务，无独立 change，
    owner 指示随批提交；SettingsView 同时携带就绪 change 的保存回调增量）。
  - **`edce9f6` feat(ui): 图谱与 wiki 生成入口界面化**（add-graph-wiki-ui-generation
    归档）：api.ts `buildGraph/generateWiki`（体 `{}` 幂等缓存路径）；图谱空态
    「构建图谱」+ 已建态「更新图谱」；wiki 空态「生成 wiki」+ 图谱缺失两段式引导
    （构建成功自动续跑）+ 已建态「重新生成 wiki」（清空旧选中）；失败在视图内展示
    中文 message（空态/已建态均有刷新失败落点）。后端零改动、无 OpenAPI 变更。
- 门禁基线：pytest **642**、vitest **68**、ruff、mypy、eslint、tsc、build、
  pre-commit 全绿。DashScope 真实冒烟（qwen-plus，env 层 + tmp 投影语料 + GUI
  黑盒点击）：构建 → 35 实体画布 → wiki 9 条目 → 更新/重新生成全缓存命中
  （llm_calls=0）。graph-wiki 笔经独立评审修复 3 缺陷（empty_corpus 不刷新、
  已建态图谱缺失静默、刷新失败无落点），详见归档 review.md 评审循环追记。
- **上报待立项（既有缺陷，非本批引入）**：① 凭证被拒（401/403）误报「请补全
  base_url/model」——需分型 `EndpointCredentialError` 三面加映射；② config.toml
  损坏同文案死路；③ serve CLI 参数启动时 ask_readiness 偏保守；④ 生成路径错误
  文案仍 CLI 导向（如 `notes_dir_missing` 提示「执行 siku ingest」），宜与 ① 同批
  做 HTTP/CLI 文案分面。均记在两份归档 review.md。
- 工作区干净；下一阶段无明确任务，未预写 openspec 骨架；开新 change 前先到
  ROADMAP 对齐排序，归档后回写勾稽。

## 已知坑

- **superseded 检疫是文件布局语义**：旧版移出 notes/ 即自然退出索引；**勿平铺**
  `vault/superseded/`（.md 的原件与投影同名互覆）。
- **`data/library.sqlite3` 是状态不是派生物**，与 `retrieval.sqlite3` 物理分离是
  tombstone 活过重建的前提。
- **身份三维派生**：source_id = sha256(暂存路径)[:12]，暂存路径含完整 dir_id——
  不截断、不去维，否则多副本串扰。
- **自动扫描检测在槽外、执行在槽内**；取消收尾衔接索引（失败诚实 failed）。
- **`ask_readiness` 判定住内核、UI 只渲染**：`missing` token 是跨语言契约，新增
  缺项时同步 `model_supply` 常量与 `ui/src/App.tsx` 的 `MISSING_LABELS`；UI 端
  `normalizeReadiness` 的 fail-open 语义勿改成阻塞式。
- **生成入口语义（graph-wiki 笔冻结，勿回退）**：按钮走幂等缓存路径，不暴露
  `rebuild=true` 与目录覆写；不做就绪门控（llm-only 就绪是触发型候选）；空语料
  也落空产物，按钮必须照常刷新数据面；`graphMissingKnown` 任何 200 都要清除。
- **手工冒烟语料必须是 `vault/notes/` 下的标准投影**（frontmatter JSON 值 +
  `## anchor` 区块；裸 md 触发 `notes_dir_missing`/解析错）；幂等验证看响应
  `llm_calls=0`；`serve --with-ui --port <非默认>` + env 层 + tmp 语料，勿用仓库内
  vault/data。
- pre-commit ruff rev 需与 uv.lock 同步升级（v0.16.8）；`mypy` 不带路径参数；
  pytest 勿在 ui/ 下跑（会收集 src-tauri 构建产物）；`siku scan` 勿与 serve 并发；
  Markdown 安全渲染唯一入口 `ui/src/markdown.ts`。

## 触发型（不主动做，全在 ROADMAP 台账有账）

Phase 6 签名与自动更新（等发布解禁决策）；Windows/Linux 实机冒烟；双通道基线补录；
三视图 Tauri 壳内界面级冒烟（等真实 BYOK 环境）；llm-only 就绪门控（若 owner 要
求生成入口置灰语义时另立项）；多设备同步 vault 强需求出现 → 同步伴侣另立项
（ADR-0010 复核信号）；purge 误删反馈显著 → tombstone 保留期策略。
