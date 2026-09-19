# 设计：桌面资料管理（导入/摄取/索引界面与进度反馈）

本文记录约束冻结决议（tasks.md「约束冻结」三项）与实现落点。apply 阶段如与本文冲突，
以本文为准修订实现，反之发现本文错误也应回改本文——两者不得静默漂移。

## 约束冻结决议 #1：资料库 API 契约

**清单 `GET /api/library` → `{sources: [...]}`**，按 `name` 排序，无分页（桌面单用户，
量级千内）。每条来源：

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | str | 展示名：投影 frontmatter `source_name`（原始文件名）；无投影时为附件文件名剥去 `--{source_id}` 后缀 |
| `path` | str | 附件相对 vault 的 POSIX 路径（`attachments/<stem>--<id><ext>`） |
| `source_hash` | str | **附件原件当前字节的 SHA-256**（宪法口径：source_hash = 原件字节哈希） |
| `ingest_status` | str | `ingested`（投影存在且 frontmatter hash == 附件 hash）/ `stale`（投影存在但 hash 不匹配，待重抽）/ `pending`（白名单内但投影缺失或损坏）/ `ignored`（扩展名不在抽取注册表白名单） |
| `index_status` | str | `indexed`（索引 manifest 中 hash 与 note_path 均未变）/ `stale`（manifest 有该 source 但 hash 或路径已变）/ `missing`（索引中没有、索引不存在或打不开） |

派生规则：以 `vault/attachments/` 为清单主体（来源真身），配对 `vault/notes/<同名>.md`
读 frontmatter（复用 `notes_reader`）；索引状态读 `SqliteIndex.source_manifest()`。
全部只读派生，不写任何文件（spec：清单为只读派生）。

**导入摄取 `POST /api/library/ingest`**：请求形状随决议 #2 选 **multipart/form-data，
字段 `files`（一个或多个）**。内核把上传字节写入确定性暂存路径后逐文件调用既有
`ingest_path(staged, vault)`，任务化执行（见决议 #3），完成后按决议衔接增量索引；
响应 200 + 任务快照。参数校验失败（缺 files / 空 filename）走既有 422
`invalid_request`。

**任务进度 `GET /api/library/jobs/{job_id}`** → 任务快照：

```json
{
  "job_id": "uuid4-hex",
  "kind": "ingest | rebuild",
  "state": "running | succeeded | failed | cancelled",
  "phase": "ingesting | indexing",
  "total": 0, "done": 0, "failed": 0,
  "current": "正在处理的文件名 | null",
  "items": [{"name", "path", "status", "detail"}],
  "error": "任务级失败中文文案 | null"
}
```

- `total/done/failed` 按文件计数；`done` 单调不减（spec：进度单调）。rebuild 任务
  无文件维度，`total=done=0`，进度只有 `phase=indexing` 的状态语义。
- `items[].status`：`created | updated | skipped | ignored | failed`；`failed/ignored`
  附中文 `detail`（技术细节只进日志）。白名单外文件按既有「忽略」语义在 items 中
  报告，不落盘、不出现在清单。
- 文件级失败不失败任务；`state=failed` 仅当索引衔接失败或未预期异常，
  `error` = 既有 `map_domain_error` 中文文案（含「需全量重建」指引等，与设置中心
  告警同一出口）。

**取消 `POST /api/library/jobs/{job_id}/cancel`**：语义见决议 #3。

**全量重建 `POST /api/library/rebuild`**：JSON `{"confirm": bool}`。缺省/false →
422 `rebuild_confirm_required`；true → 启动 `kind=rebuild` 任务（`sync_index(rebuild=True)`
整体单步），复用任务快照轮询。摄取与重建共用单任务槽，互斥 409。

**新增稳定错误码**（归入既有三类状态）：

| 状态 | code | 场景 |
|---|---|---|
| 409 | `library_job_busy` | 已有任务（摄取或重建）在跑时再次触发 |
| 409 | `library_job_not_running` | 取消一个非运行中任务 |
| 404 | `job_not_found` | 任务 id 不存在（含进程重启后旧 id） |
| 422 | `rebuild_confirm_required` | 重建未携带确认标记 |

OpenAPI 快照经既有 `uv run python -m siku.api.contract --refresh` 显式刷新。

## 约束冻结决议 #2：导入的文件交接方式

**选择：浏览器 file picker 上传字节流（multipart）由内核落盘**；不做 Tauri 原生
路径桥接。

裁决依据（apply 时补充的关键事实）：桌面壳（已归档的 desktop-shell change）主窗口
先加载本地 splash 页、随后导航到 sidecar 同源页（`http://127.0.0.1:<port>`），其
capability 明示**问答页面无任何 IPC 权限是设计意图**（壳零业务、攻击面最小）。若走
原生选择器产路径，必须给远程源（127.0.0.1 页面）开 Tauri IPC 并新增 dialog 插件
权限——正是壳变更刻意回避的权限面扩大，且壳代码属已归档 change 的领地。

上传方案的合规性：语料字节经 localhost HTTP **直达内核**，webview 只做字节搬运、
不解析不处理（红线 2「UI 只经 HTTP」满足；ADR-0001 的实质「业务逻辑不进壳/UI、
语料不经 invoke/事件」满足）；浏览器 dev 与 Tauri webview 同一代码路径，无环境
检测与降级分支。代价是大文件多一次暂存落盘（loopback 场景可接受）。

**幂等保真**（tasks：同 source_hash 重跑 skip）：暂存路径按
`<系统临时目录>/siku-uploads/<sha256(字节)前12位>/<原始文件名>` 确定性命名——
同内容同名重导入 → 同暂存路径 → 同 `source_id`（既有管线按路径字符串派生）→
同附件名同投影名 → 既有管线 hash 相同 skip。暂存文件在任务内逐个用毕即删；
进程崩溃残留属系统临时目录垃圾，无害。文件名只取 `Path(filename).name`（防路径穿越）。

## 约束冻结决议 #3：摄取任务生命周期

- **单任务槽**：进程内单工作线程（daemon `threading.Thread`），一次只跑一个任务，
  与 CLI 串行语义一致，避免 SQLite 写竞争；重复触发 409。
- **失败持久化表现：仅在任务结果中呈现**（items + error），不向 vault 落任何失败
  元数据（红线 3：vault 只存语料事实；失败是任务过程信息，任务状态只存内存）。
  失败来源在清单中因投影缺失自然呈 `pending`，下次重跑幂等补齐。
- **取消：尽力取消 + 幂等兜底**。协作式、文件粒度：`cancel` 只设标志，**当前文件
  处理完毕后**停止，剩余文件不再处理（`state=cancelled`、`done < total`），已完成
  部分保留；取消后不衔接索引。重跑按 `source_hash` 跳过已完成文件（幂等兜底）。
  索引阶段（`sync_index` 原子切换单步）不可中断：取消请求在索引阶段到达时任务正常
  跑完。
- **进程重启恢复**：任务状态只存内存，重启即消失（旧 job_id 404）；用户重新触发 =
  幂等重跑，spec 场景「管线按 source_hash 跳过已完成文件并完成剩余部分」由既有
  管线保证。
- **索引衔接**：摄取文件阶段结束且无取消、且 items 中存在 `created/updated` 时，
  自动以 `rebuild=False` 调索引器；全部 skipped/ignored/failed 时不触发（无新内容，
  且避免 embedding 未配置时无谓报错）。索引器失败 → 任务 `failed` + 既有中文指引
  （`ModelConfigMismatchError` → 「请执行全量重建」，与设置中心告警同一出口）。

## 实现落点

- `src/siku/api/library.py`（新）：清单推导 + `LibraryJobManager`（单任务槽、协作
  取消、进度快照）+ 暂存落盘。
- `src/siku/api/models.py`：`LibrarySourceResponse` / `LibraryResponse` /
  `LibraryJobItemResponse` / `LibraryJobResponse` / `LibraryRebuildRequest`。
- `src/siku/api/app.py`：`index_runner` 注入点（`Callable[[bool], IndexReport]`，缺省
  = 每任务现解析 embedding 通道 + `sync_index` + 关闭 provider，与 LLM 每请求现解析
  同口径，设置写入后免重启生效）；五个端点挂载。
- 错误映射全部复用 `messages.py` 既有表；新端点码在端点内联（同 settings 端点先例）。
- UI：`ui/src/LibraryView.tsx`（新）+ `api.ts` 类型与函数 + `App.tsx` 第三个导航页
  「资料库」+ `styles.css` 增量样式；轮询用递归 `setTimeout`（卸载清理），任务结束
  自动刷新清单。

## 已知取舍

- 清单每次计算附件 SHA-256（O(vault 大小)）：清单只在进入视图与任务结束后拉取，
  不轮询，本地磁盘可接受。
- 索引 manifest 读取与后台 `sync_index` 的 `os.replace` 存在极窄并发窗口：POSIX 上
  旧句柄读旧版本无害；Windows 上 replace 撞打开句柄会失败——Windows 实机支持属
  Phase 6 触发项，此处不预先复杂化。
- 上传进度不做字节级反馈（fetch 原生行为），进度反馈从摄取 job 开始；spec 只约束
  摄取进度。
