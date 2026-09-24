# 评审：来源目录同步（add-directory-sync）

## 评审方式

apply 完成后由独立子代理对全部变更做整轮评审（规格 deltas + ADR-0010 + 实现 +
测试逐文件比对，两处疑点在 /tmp 环境做了可复现性验证）。评审发现 2 阻断（B1/B2）、
3 应修（A1/A2/A3）、7 建议（S1–S7）；本轮返工采纳 B1/B2/A1/A2/A3 全部、S1/S2/S3/
S4/S5/S7 采纳，修复后复验全绿。以下记录缺陷、修复与验证证据。

## 阻断缺陷与修复

- **B1（已复现）tombstone 状态机漏洞——内容回退（A→B→A）后旧标记残留，purge 会
  连带删除在役当前版**。修复：`service._run_ingest_op` 摄取成功后对
  `new_source_id` 执行 `delete_tombstones` 并删除其检疫副本
  （`_remove_quarantined_copies`）。回归测试：
  `test_content_rollback_clears_tombstone_and_quarantine_copy`。
- **B2 扫描/清理任务体无顶层异常兜底——未预期异常使任务线程消亡、state 停在
  running，单任务槽永久 409 直至重启**。修复：`_run_scan`/`_run_purge` 顶层
  try/except → 任务 `failed` + 中文 error，与既有任务体同口径。回归测试：
  `test_scan_runner_crash_fails_job_and_releases_slot`。

## 应修缺陷与修复

- **A1（已复现）改名识别可吞掉「内容已变更的已登记文件」**：配对目标收窄为无登记
  的新路径（`new_only`），并从 fresh 剔除已配对目标（防其重复入库）。回归测试：
  `test_rename_does_not_swallow_changed_registered_file`。
- **A2 规格静默漂移——自动扫描的检测阶段占用了任务槽（违反 delta spec SHALL 与
  design 决议 #3）**。修复：`SyncService` 拆分 `plan_cycle`（槽外只读检测）与
  `execute_cycle`（槽内执行）；调度线程每轮先 plan，`has_work` 才取槽执行，槽忙
  丢弃本轮计划下轮重检（幂等）。`SourcePlan.has_work` 由测试专用转为生产接线。
- **A3 purge 在 unlink 失败时仍删除 tombstone**——检疫文件永久滞留失去清理入口。
  修复：删除失败时保留 tombstone、条目计 failed、不计入删除数。回归测试：
  `test_purge_failure_retains_tombstone_for_retry`。

## 建议采纳情况

- S1 采纳：registry 全部连接改 `closing` 显式关闭，不依赖引用计数兜底。
- S2 采纳：并发注册同一真实路径的 `IntegrityError` 归一为 409。
- S3 采纳：注册校验扩展——来源目录与 vault 重叠（含把 vault 自身登记为来源）
  一律 422 拒绝（`_paths_overlap`），杜绝自喂养环。
- S4 采纳：`siku scan` docstring 标注勿与运行中的 serve 并发执行。
- S5 采纳：任务结束刷新来源区、重新展开强制重取（「上次扫描」不再冻结）；
  扫描结果文案按「动作数」诚实计数（检疫移位与入库同为 updated，不再混称入库）。
- S6 说明：`messages.py` 的 LLM 未配置文案改写是本 change 之前 owner 点名的独立
  修复（未随此前工作提交），不属于本 change 范围，随本次工作树一并留待提交；
  `graphify-out/` 为会话开始前即存在的未跟踪杂散目录，不随本 change 提交。
- S7 采纳：新增调度器 lifespan 集成测试（`with TestClient` + 间隔 1 秒真实自动
  入库）及 B1/A1/A3/B2 回归测试。

## 验证证据（返工复验后）

- `uv run pytest`：**627 passed**（既有 586 + 本 change 新增 41），0 失败。
- `uv run ruff check src tests` / `ruff format --check`：全绿。
- `uv run mypy src tests`：Success（106 files）。
- `uv run pre-commit run --all-files`：8 hooks 全 Passed。
- `ui`: `npm run lint` ✅、`npm run test` 47 passed、`npm run build` ✅。
- `openspec validate add-directory-sync --changes --strict`：1 passed。
- OpenAPI 快照经 `uv run python -m siku.api.contract --refresh` 显式刷新，
  契约漂移测试（快照冻结）通过；变更仅限本 change 声明的新端点、清单字段、
  scan-settings 端点与 job 枚举扩展。
- **serve 级真实冒烟**（uvicorn 8931 + curl，/tmp 环境）：注册来源 → 间隔改 2 秒
  → 自动扫描 4 秒内入库（清单含 origin_path）→ 改内容 → 下一轮自动超替（清单
  出现 ingested + superseded，检疫目录 `superseded/{attachments,notes}/` 分层
  正确）→ purge 未确认 422、确认后物理清理 → 清单回落为在役版。冒烟中暴露
  「间隔改小需等满旧周期」缺陷，已改 1 秒粒度切片等待修复并于本轮冒烟复验。

## 遗留（触发型，不阻断归档）

- Tauri 壳内界面级点击冒烟（等真实 BYOK 环境触发项，沿袭既有台账）。
- `siku scan` 与 serve 并发互踩为既有 `siku index` 同类 hazard，已在 docstring
  标注；如需进程间互斥另开 change。

## 第二至四轮评审记录（评审迭代循环）

- **第二轮（全覆盖复审）**：1 阻断 R1（`plan_cycle` 在槽外执行 reconcile 文件移位，
  与槽内摄取/清理竞态可静默丢档，已复现）+ 2 应修 R2（同名同内容多上游副本共享
  source_id，超替串扰，已复现）R3（origin_path「SHALL NOT 含字段」与实际返回 null
  不符）。全部修复：R1 → reconcile 移入 `execute_cycle` 槽内执行、`plan_cycle`
  收敛为纯只读、新增 `pending_reconcile()` 供调度侧探测待对账情形；R2 → 暂存名
  引入来源身份与相对路径维度；R3 → 规格措辞与行为对齐（字段恒在，手动导入为
  null）。另采纳建议：scanner 哈希读盘竞态防护、CLI scan 顶层兜底与失败项非零
  退出、调度器独立停止事件、UI 来源区加载失败独立文案与间隔措辞。
- **第三轮（验证型）**：确认 R1/R3 修复有效；发现两项修复自身缺陷（均已复现）：
  调度器 Event 修复无效（`_loop` 动态读 `self._stop`，stop 超时后老线程复活成
  双循环）→ 改为 Event 以参数绑定进线程（`_loop(stop_event)`）+ 类属性
  `_JOIN_TIMEOUT_SECS: float` 供测试覆写；R2 修复跨来源不完整 → 暂存路径追加
  `<dir_id 前 8 位>` 来源命名空间。各补回归测试。
- **第四轮（收尾验证）**：两处修复经回退-恢复闭环验证（回退后对应回归测试必
  FAILED，恢复后通过，测试钉住力确认）；`relative_to` 无异常路径、dir_id[:8]
  碰撞量级 ~10⁻⁶（百源）可接受、discard_staged 嵌套清理有效、design/spec/models/
  快照四处口径一致。代码零缺陷；文档级应修一处（design.md #2 第 6 条「与手动
  上传共享身份」为过期表述，来源命名空间后已为独立文档）已修正。
- **终态**：四轮循环收敛，无阻断/应修级真实缺陷残留；取消任务不衔接索引收尾为
  既有既定取舍（desktop-library 决议 #3），自动路径下轮补齐，不翻案。

## 追加裁决轮（owner 依技术决策准则重审两条「有据取舍」，均翻案）

- **取消收尾衔接索引（翻案修复）**：原裁定「沿袭 ingest 取消语义、自动路径下轮
  补齐」经行为核验不成立——已入库文件登记 linked 后，下轮 diff 无变更即永不触发
  索引，实际是无限期不可检索；取消的 purge 亦让删除意图悬置。修复：取消只停止
  尚未开始的工作，已提交事实一律经 `_finish_with_index(cancelled=True)` 衔接增量
  索引发布（ingest/scan/purge 三类任务统一，显式修订 desktop-library 决议 #3，
  记录于 design.md 决议 #3）；索引失败 → 任务 failed 并附既有指引（取消亦诚实
  呈现）。回归：`test_cancelled_scan_still_publishes_committed_changes` +
  `test_cancel_stops_after_current_file` 断言更新（calls == [False]）。
- **dir_id 截断（翻案修复）**：`<dir_id 前 8 位>` 改为完整 32 位 dir_id——截断
  唯一收益是临时目录名短两个字符，却保留可预见的身份合并故障类（叠加同内容同
  相对路径即复现 R2 串扰）。design.md 决议 #2 第 6 条同步改写。
- 门禁复验：pytest 627 / ruff / mypy / pre-commit / UI lint+47test+build /
  openspec strict 全绿；OpenAPI 无契约变化。
