# 提案评审

- 状态：仅提案，HTTP/CLI/UI、选择式清理、索引消减与写锁尚未实现，全部实施任务未勾选。
- 必要性：普通手动文档不属于现有 missing/superseded 清理集合，没有单项退出入口。
- 复用裁决：沿用清理内核、tombstone、任务进度与索引发布机制，不增加回收站、删除历史或通用工作流。
- 关键边界：用同步登记判归属，保留外部原件，只处理选定来源；新移除 reason 不能冒充上游缺失。
- 完整性：无需当前 BYOK 的索引消减、旧图谱/Wiki 失效与跨进程写入互斥均为正确移除所需，不是新增用户功能。
- 失败语义：文件与索引无跨介质原子事务，完整收尾前保留确认标记；失败或取消不能误报成功。
- 提案严格校验与只读复核结果记录在本轮 HANDOFF；实现时必须完成安全、质量和完整链路门禁。

## 本轮验证（2026-10-02）

- 本件及本轮全部 7 件 change 的 OpenSpec 严格校验通过；对应 library-sync、http-api、web-ui、graph-wiki 的临时预合并规格严格校验通过，未写入主规格。
- MODIFIED 原 Requirement/Scenario 名称保留检查、局部文档链接、任务未勾选、文档变更范围及 `git diff --check` 均通过。
- 只读方案复核已完成，必要修正写回设计、规格和实施回归；收款继续 Mock。
- 本轮没有业务代码、依赖或迁移变更，未运行编译、业务测试、UI 实机或打包验收，不把提案通过记成实现完成。

## 实施验证（2026-10-02）

- 内核：`sync/removal.py`（资格判定/写入口统一前置/快照失效）、`sync/locking.py`
  （filelock 平台文件锁，`vault/.siku/library.lock` 非语料位置）、
  `retrieve/reduction.py`（无模型按来源消减：复用临时构建+剩余来源复制+向量行
  复用+旧元数据保真；两段式发布与暂存对恢复状态机）。`SyncService.run_removal`
  完整收尾管线（标记 → 文件 → 暂存消减 → 发布 → 快照失效 → 清标记）；
  `run_purge` 支持 `source_ids` 选择式清理，`user_removed` 无论入口都走同一
  完整收尾；`execute_cycle` 锁后重验来源登记，陈旧计划整组丢弃。
- 入口：`POST /api/library/remove`（422 `remove_confirm_required` / 404
  `source_not_found` / 409 `source_sync_managed` / 409 `library_job_busy`，
  进度沿既有 LibraryJobs 契约，kind=`remove`）；清单条目带真实 `source_id` 与
  服务端 `removable`，未完成移除合成「移除未完成」行（可按原 ID 重试）。
  CLI `siku remove SOURCE_ID --confirm`（--json 支持同一内核）。同库写入互斥覆盖
  资料库导入/重建/扫描/清理/移除、原始 `/api/ingest`、`/api/graph`、`/api/wiki`、
  来源启停/解除登记与 CLI ingest/index/graph/wiki/scan/remove；写入口第一步完成
  中断消减的向前发布（普通构建不误删可恢复暂存对）。
- UI：行内「从资料库移除/重试移除」、确认框（外部原件保留 + 图谱/Wiki 重建说明）、
  任务进度与失败重试态、成功后刷新清单并通知 App 清理知识缓存（提问建议等
  派生缓存按纪元重取）；类型与 `contracts/openapi.json` 同步导出
  （`siku.api.contract --refresh`，漂移测试门禁通过）。
- 测试：`test_sync_removal.py` 18 例（资格判定、选择式清理、外部原件保留、符号
  链接越界、无 BYOK 消减、向量已切 SQLite 未切的无模型恢复、普通构建不删可恢复
  暂存、重建不复活、部分失败重试接续、取消撤销新标记、全量清理完整收尾、同进程
  与真实两进程互斥、扫描锁后重验、HTTP 契约、未完成移除行、PDF 端到端）；
  LibraryView 组件测试 5 例（资格展示、确认文案与取消零写入、成功链路+缓存失效
  通知、未完成重试入口、失败不谎报成功）。全量 pytest 796 通过、ruff 干净、
  UI vitest 114 通过、`tsc -b`/`eslint`/`vite build` 通过、OpenSpec 严格校验通过。
- 已知边界（如实登记，非缺陷豁免）：CLI `siku wiki` 无 `--vault` 参数，非默认
  vault 布局下与移除的互斥以默认 vault 锚定（serve 侧全量正确）；全量 purge 中
  missing/superseded 的索引追平仍沿既有任务收尾增量同步（依赖当时 BYOK 可用），
  `user_removed` 不受该依赖影响。

## 第二轮验证补充（2026-10-02）

- 独立子代理评审确认 5 项缺陷，全部修复并带回归测试（pytest 全量 801 通过）：
  1. 相对路径 vault（CLI/serve 默认布局）被越界防御误拒 → 改为双侧 resolve 比较；
  2. 无消减标记的崩溃残片砖化全部写入口（含 index --rebuild）→ 无标记即按残片清理放行；
  3. 恢复步骤异常导致任务线程带异常死亡、单任务槽永久 409 → 顶层兜底落 failed 终态；
  4. CLI scan 衔接索引在写锁外，可摧毁另一进程的可恢复暂存对 → 扫描+索引并入同一
     写锁作用域（docstring 的「不要与 serve 并发」旧口径随之作废）；
  5. 仅 user_removed 的全量清理在 BYOK 不可用时被误报 failed → 该场景收尾不再
     衔接 provider 相关增量同步。另删无调用方的 library_write_session 冗余入口。
- UI 验收（4.4）：真实 serve + 种子库（手动/同步/混合态）三视口验收通过；键盘路径
  依赖原生 button 语义 + 组件测试（内嵌浏览器对 Mantine Modal 的合成事件不可靠，
  可信点击已验证既有模态交互正常）。同轮修复既有「来源目录」行 Switch 轨道顶贴
  缺陷（`.mantine-Switch-body` 恢复 `align-items: center`，一属性修复，零装饰样式）；
  实测 trackCenterDelta=0。
- 亮暗两态同 change 1 结论：产品为 light-only，登记为待 owner 决策项。

## 代码审查迭代循环（2026-10-02，评审范围=全部未提交变更）

- 第二轮全覆盖自查在 CLI `scan` 发现 1 项真缺陷并修复：锁忙时 `_fail` 抛出的
  `typer.Exit`（click Exit 继承 RuntimeError）被 `except Exception` 吞掉后二次
  误报「扫描执行失败」——补 `except typer.Exit: raise` 透传，回归用例
  `test_cli_scan_busy_reports_single_actionable_message` 锁定（stderr 仅一条
  互斥提示、无二次误报）。
- 其余复查面（reduction 状态机、removal 前置、任务管理器锁生命周期、端点
  错误码、UI 走线、抽取器、构建脚本、契约快照）无新增可检缺陷。
- 门禁：pytest 802 通过、ruff check/format 干净、UI vitest 114 + tsc +
  eslint + build 通过、OpenSpec specs 8/8、`git diff --check` 干净。
