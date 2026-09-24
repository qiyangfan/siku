# 设计：来源目录同步（受管喂养 + 定时扫描 + 标记式删除）

本文记录约束冻结决议与实现落点。apply 阶段如与本文冲突，以本文为准修订实现，
反之发现本文错误也应回改本文——两者不得静默漂移。方向性裁决（为什么是受管喂养、
为什么轮询、为什么标记式删除）见 ADR-0010，本文只记契约与算法。

## 约束冻结决议 #1：库域状态库（`data/library.sqlite3`）

WAL 模式、全参数化 SQL（`?` 占位）。命名对齐既有 `retrieval.sqlite3`。**非派生
物**：索引/图谱/wiki 的任何重建 SHALL NOT 触碰它。表结构：

```sql
-- 来源目录注册表（path 存绝对路径；判重用 resolve() 后的真实路径）
CREATE TABLE sync_sources (
  id            TEXT PRIMARY KEY,          -- uuid4 hex
  path          TEXT NOT NULL UNIQUE,
  enabled       INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL,
  last_scan_at  TEXT                       -- ISO8601；仅扫描实际执行后更新
);

-- 变更检测缓存：上游路径 → 受管文档（state: linked | unlinked）
CREATE TABLE sync_entries (
  dir_id        TEXT NOT NULL,
  upstream_path TEXT NOT NULL,             -- 来源目录内的绝对路径
  doc_source_id TEXT NOT NULL,             -- 与 vault 既有 source_id 同域
  content_hash  TEXT NOT NULL,
  size          INTEGER NOT NULL,
  mtime_ns      INTEGER NOT NULL,
  state         TEXT NOT NULL,
  PRIMARY KEY (dir_id, upstream_path)
);

-- tombstone：被标记待清理的受管文档（reason: superseded | missing）
CREATE TABLE sync_tombstones (
  doc_source_id TEXT PRIMARY KEY,
  reason        TEXT NOT NULL,
  superseded_by TEXT,                      -- reason=superseded 时的替代版本
  marked_at     TEXT NOT NULL
);

-- 库域设置（目前仅扫描间隔；≤0 = 关闭自动扫描）
CREATE TABLE sync_settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```

要点：tombstone 只存"哪个 `source_id` 被标记"，不复制任何文档事实（清单状态仍从
vault 元数据 + 登记派生）；`doc_source_id` 与既有摄取管线按路径串派生的
`source_id` 同域，purge 时可据此定位 attachments/notes 文件。

## 约束冻结决议 #2：扫描算法（对每个 enabled 源）

1. 递归枚举目录：跳过点前缀条目与符号链接（防环、防越权读取）；扩展名不在摄取
   注册表白名单 → 按既有"忽略"语义记录，不登记。
2. **源不可达保守护栏**：枚举抛错，或登记非空但本轮可枚举文件数为 0 → 判定源
   不可达，本轮顺延该源并在扫描结果中记录，不做任何标记（防卸载/断连被误判为
   批量删除）。
3. 对每个登记条目先比 `(size, mtime_ns)` 快选：未变 → 跳过（不重算哈希）；变化
   或新文件 → 计算 SHA-256。
4. diff 结果：
   - **新文件** → copy-in（确定性暂存 `<系统临时目录>/siku-uploads/<sha256 前
     12 位>/<完整 dir_id>/<来源内相对路径>`，身份派生方式见第 6 条）→
     既有 `ingest_path` → 登记 `linked`。
   - **哈希变化** → copy-in 新版本入库 → 旧文档写 tombstone（reason=superseded，
     superseded_by=新 source_id）→ **旧文档文件移入检疫目录 `vault/superseded/`**
     （原件与投影同移）。
   - **登记条目消失** → 改名识别：同源目录内本轮出现同 `content_hash` 的新路径
     → 视为移动，仅更新登记的 `upstream_path`；否则登记转 `unlinked`，对应文档
     写 tombstone（reason=missing，文件留在原位）。
5. **superseded 检疫目录（apply 期修正）**：`sync_index` 以 `vault/notes/` 现状为
   唯一清单源（临时库全量重建式同步），文件离开 notes/ 即自然退出索引、任何全量
   重建也不会复活——因此 superseded 的「退出检索」用**文件布局**表达（移出
   notes/ 与 attachments/，字节保留在 `vault/superseded/{attachments,notes}/`，
   按原角色分层——Markdown 源的原件与投影同名，平铺会互相覆盖丢失原件字节），
   不为剔除语义改动 `sync_index` 契约、也不出现「CLI `siku index` 重建复活已退
   检索文档」的漏洞。清单相应扫描 `vault/superseded/attachments/` 以呈现
   `superseded` 徽标直至清理。tombstone 行先写、文件后移：进程中断时下轮扫描
   开头的**对账步骤**（补移仍留在 attachments/notes 的已标记文档）自愈。
6. **暂存名含来源身份与来源内相对路径（第二/三轮评审 R2 修正）**：暂存路径 =
   `<sha256 前 12 位>/<完整 dir_id>/<来源内相对路径>`，身份在内容哈希之上叠加
   来源与相对路径两个维度。来源维度用完整 32 位 dir_id 而非截断——截断省的
   只是临时目录名两个字符，却把可预见的身份合并故障类留在系统里（第四轮评审
   后 owner 裁决翻案）。不同来源目录（乃至同源不同子目录）的同名同内容文件
   是**两份独立文档**——若共享 id，对其一的内容变更会把另一份未变更文件的在役
   文档整体移入检疫区，状态机的 entry↔文档一对一假设被打破且永不自愈。手动
   上传（stage_upload）命名保持 `<hash12>/<文件名>` 不加命名空间，避免既有上传
   source_id 迁移；来源文件（含根级）经来源命名空间后，与手动上传同名同内容
   亦为独立文档。同源目录内移动仍由第 4 步改名识别兜住，不产生重复文档。
7. **对账（补移中断的检疫移位）是 vault 变更，只在任务槽内执行**（`execute_cycle`
   开头；第二轮评审 R1 修正）：调度线程的 `plan_cycle` 必须保持纯只读——reconcile
   与槽内摄取/清理并发，会把刚写好的在役文件移入检疫并被同 id 副本清理删除，
   造成静默丢档。调度侧以 `pending_reconcile()` 探测待对账情形，有对账需求时
   同样取槽执行。

同内容不同文件名（或同文件名不同来源位置/不同子目录）→ 身份（内容哈希 + 来源
身份 + 来源内相对路径派生）不同 → 两份独立文档。这与手动导入语义一致，本 change 不新造去重规则；上游改名
由步骤 4 的移动识别兜住，不会因改名产生重复文档。

## 约束冻结决议 #3：调度与任务槽

- serve 启动 daemon 调度线程（lifespan 启停）；每轮开始读 `scan_interval_secs`
  （免重启生效）；`≤0` → 本轮跳过（线程以 `Event.wait` 挂起，可被间隔修改唤醒）。
- **自动路径**：只读 diff 不占任务槽；存在待执行变更时尝试取槽，槽忙 → 本轮
  顺延（英文日志，无用户可见错误）。
- **手动路径**（`POST /api/library/scan`）：直接取槽执行完整一轮（含 diff），
  槽忙 → 409 `library_job_busy`（复用既有码）；无变更 → 瞬时 succeeded 任务
  （items 为空）。请求体 `{full?: bool}`：full=true 跳过 stat 快选、强制全量
  哈希校验（怀疑 stat 漏检时的逃生门，如 mtime 被工具批量重写的原地改写）。
- 任务 `kind` 枚举扩展 `scan | purge`；`phase` 扩展 `scanning | purging`；进度、
  协作取消、重启后幂等恢复语义全部复用既有任务机制（重启后登记与 tombstone 在
  库域状态库中持久，重新扫描天然幂等补齐）。

## 约束冻结决议 #4：API 契约

| 端点 | 语义 |
|---|---|
| `GET /api/library/sources` | `{sources: [{id, path, enabled, created_at, last_scan_at}]}`，按 path 排序 |
| `POST /api/library/sources` | `{path, enabled?}` → 200 快照；目录不存在/非目录 → 422 `invalid_request`；resolve 后同真实路径 → 409 `source_already_registered` |
| `PUT /api/library/sources/{id}` | `{enabled}` → 200 快照；未知 id → 404 `source_not_found` |
| `DELETE /api/library/sources/{id}` | 200 `{removed: true}`；只删登记与缓存，已入库文档与 tombstone 不动；未知 id → 404 |
| `POST /api/library/scan` | 200 任务快照（kind=scan）；槽忙 → 409 `library_job_busy` |
| `GET /api/library/scan-settings` | `{interval_secs}`（当前自动扫描间隔；缺省 300） |
| `PUT /api/library/scan-settings` | `{interval_secs}`：≥0 合法（0 = 关闭自动扫描）→ 200 新值，调度线程每轮现读即免重启生效；负数 → 422 `invalid_request` |
| `POST /api/library/purge` | `{confirm}`：缺省/false → 422 `purge_confirm_required`；true → kind=purge 任务：物理删除全部 tombstone 文档（`vault/superseded/` 检疫文件，或 reason=missing 时原位的 attachments 原件 + notes 投影），增量索引即时消减，删对应 tombstone 行；图谱/wiki 经既有重建流程再生 |

`GET /api/library` 清单条目扩展：`ingest_status` 枚举增加 `missing`（附件原件
缺失，投影仍在）与 `superseded`（被新版本替代、文件在 `vault/superseded/` 检疫、
已退出检索）；由喂养同步而来的条目附可选 `origin_path`（登记的上游路径；手动导入
该字段为 null，superseded 条目取 tombstone 上记录的来源路径）。任务条目 `status` 枚举
增加 `removed`（purge 已物理清理；apply 期显式声明扩展）。CORS `allow_methods`
同步增加 `DELETE`（来源移除端点；对既有端点无影响）。

新增稳定错误码：409 `source_already_registered`、404 `source_not_found`、
422 `purge_confirm_required`；既有 409 `library_job_busy`、422 `invalid_request`
复用。OpenAPI 快照经 `uv run python -m siku.api.contract --refresh` 显式刷新。

## 约束冻结决议 #5：重算事件边界（spec 级红线）

- 定时扫描 SHALL 只做变更检测、入库与对账；SHALL NOT 触发全量重嵌、全量重抽、
  图谱重建或 wiki 生成。增量索引只伴随本轮实际入库/清理变更发生。
- embedding 模型身份变更仍走既有设置告警 + 显式全量重建出口，本 change 不新增
  任何重算触发器。

## 实现落点

- `src/siku/sync/`（新包）：`registry.py`（决议 #1 的 SQLite 状态层）、
  `scanner.py`（决议 #2 的 diff 算法，纯函数便于测试）、`service.py`
  （scan/purge 任务体，供既有 `LibraryJobManager` 执行）。
- `src/siku/api/library.py`：任务管理器扩展 kind/phase；sources/scan/purge
  处理函数。
- `src/siku/api/app.py`：端点挂载 + 调度线程 lifespan 启停；扫描器与注册表经
  `application.state` 注入（测试可替换 tmp 目录）。
- `src/siku/api/models.py`：请求/响应模型。
- `src/siku/cli.py`：`siku scan`（一次性同步扫描，typer.echo 中文报告）。
- UI：`ui/src/LibraryView.tsx`（来源目录区 + 扫描/清理控件 + 新徽标 +
  origin_path 展示）、`ui/src/api.ts`（类型与函数）；错误映射沿用 messages.py
  与端点内联先例。

## 已知取舍

- stat 快选信任 `(size, mtime_ns)`：绕过 mtime 的原地改写会漏检；提供手动扫描
  `full=true` 全量哈希逃生门，不为个人文档场景预置持续全量校验。
- 单线程轮询无抖动补偿：个人库无 SLA 诉求，间隔秒级粒度足够。
- purge 直接删除，不做第二级回收站：tombstone 本身是缓冲层（标记与物理删除之间
  有一道人工确认），双确认已达标。
- 扫描检测与摄取任务并发窗口（diff 后文件再变）：摄取按当时字节哈希记账，下轮
  扫描按登记哈希再次检出并超替，最终一致。
