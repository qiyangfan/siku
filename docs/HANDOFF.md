# HANDOFF — siku 交接文档

> **接驳点，非常驻知识库。** 常驻知识分属四层：宪法 `openspec/project.md`、协作规范
> `AGENTS.md`、路线 `docs/ROADMAP.md`、相关决策 `docs/adr/`。本文件每次交接整体重写，
> 只写接手者马上需要的状态。

- **更新时间**：2026-09-24（第十三次，add-directory-sync 已归档提交推送）
- **仓库**：`~/siku` → github.com/qiyangfan/siku（私有；SSH 推送，gh keyring 认证）

## 现状

- **`2026-09-24-add-directory-sync` 已归档**（library-sync spec 入主 specs，8 个
  spec strict 全过）并已提交推送。交付：`siku.sync` 内核包（registry/scanner/
  service）、`data/library.sqlite3` 库域状态库（非派生物，重建不清除）、serve 内置
  轮询调度（检测在槽外/执行在槽内，间隔免重启生效）、`/api/library/sources|scan|
  scan-settings|purge` 端点、清单扩展（missing/superseded/origin_path）、`siku scan`
  CLI、资料库视图来源目录管理区。核心语义见 ADR-0010：来源目录只读单向 copy-in；
  超替 = tombstone + 移入 `vault/superseded/{attachments,notes}/`（借文件布局退出
  索引，重建不复活）；物理删除仅显式 purge；定时路径零模型调用。
- **评审循环四轮 + owner 追加裁决一轮**全部闭环：修复阻断 2（reconcile 槽外竞态
  静默丢档、内容回退残留标记致 purge 误删在役版）、应修 5（任务体异常卡死单任务
  槽、改名配对吞变更、检测占槽违反 spec、purge 失败清标记、跨来源身份混叠）及
  修复自身缺陷 2（调度器 Event 复活、跨来源命名空间）。owner 依技术决策准则翻案
  两条取舍：**取消收尾衔接索引**（修订 desktop-library 决议 #3，`_finish_with_index
  (cancelled=True)`）与 **dir_id 用完整 32 位**（不截断）。证据见归档件 review.md。
- 顺带入库：`messages.py` 问答未配置 key 文案改为引导「设置」页（owner 此前点名）。
- 本笔验证：pytest **627**（+41 新增）、ruff check/format、mypy、pre-commit、UI
  lint/test 47/build、openspec strict、serve 级真实冒烟（uvicorn+curl 全链路）全绿。
- **下一阶段无明确任务，未预写 openspec 骨架**：Phase 6 签名与自动更新等发布解禁
  决策；触发器台账全等外部环境。开新 change 前先到 ROADMAP 对齐排序。
- `graphify-out/` 为未跟踪杂散目录，不属本仓库交付物，勿提交勿删除（待 owner 处置）。

## 已知坑

- **superseded 检疫是文件布局语义**：旧版移出 notes/ 即自然退出索引，重建不复活；
  清单扫 `vault/superseded/attachments/`。**勿平铺检疫目录**（.md 源的原件与投影
  同名，平铺互相覆盖丢原件字节）。
- **库域状态库 `data/library.sqlite3` 是状态不是派生物**，与 `retrieval.sqlite3`
  物理分离是 tombstone 活过重建的前提。
- **身份三维派生**：来源文档 source_id = sha256(暂存路径)[:12]，暂存路径 =
  `<hash12>/<完整 dir_id>/<来源内相对路径>`——不截断 dir_id、不去掉任何一维，
  否则同名同内容多副本重新串扰（评审 R2/R3-2）。
- **取消收尾衔接索引**（决议 #3 修订）：三类任务的取消都走增量索引发布已提交
  事实；索引失败 → 任务 failed 诚实呈现，不伪装成 cancelled。
- **自动扫描检测在槽外、执行在槽内**（spec SHALL）：`plan_cycle` 必须纯只读；
  调度 1 秒切片，间隔修改 ≤1 秒生效；槽忙丢计划下轮重检；`pending_reconcile`
  探测待对账情形。
- 扫描 quick-check 锚点 (size, mtime_ns) 逃生门：`POST /api/library/scan
  {"full":true}` / `siku scan --full`；与 `AttachmentDigestCache` 同级信任，
  不得用于事实层决策。
- `siku scan` 勿与运行中的 serve 并发（索引临时目录互踩，同 `siku index` 类
  hazard）；CLI 不做来源 CRUD（登记走 Web 资料库）。
- 读取面错误语义边界（`reading.py` docstring 权威）、Markdown 安全渲染唯一入口
  `ui/src/markdown.ts`、前端防竞态用独立请求序号 ref、`mypy` 不带路径参数、pytest
  勿在 ui/ 下跑——沿袭既有归档件，不赘述。
- 手工冒烟缺真实模型时：openai 兼容 mock（/embeddings + /chat/completions）即可
  跑通全链路，做法见归档 review.md 冒烟段。

## 触发型（不主动做，全在 ROADMAP 台账有账）

Phase 6 签名与自动更新（等发布解禁决策）；Windows/Linux 实机冒烟；双通道基线补录；
三视图与来源目录区 Tauri 壳内界面级冒烟（等真实 BYOK 环境）；多设备同步 vault 强
需求出现 → 同步伴侣另立项（ADR-0010 复核信号）；purge 误删反馈显著 → tombstone
保留期策略。
