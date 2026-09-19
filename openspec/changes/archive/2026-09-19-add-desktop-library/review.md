# Review：桌面资料管理（add-desktop-library）

apply 完成后的独立复核记录。任务生命周期、幂等恢复与索引衔接的验证证据见
`tests/test_api_library.py`（13 项契约测试）与下方冒烟记录。

## 约束冻结决议落点（详见 design.md）

- **决议 #1（API 契约）**：`GET /api/library`（清单四态摄取状态 × 三态索引状态）、
  `POST /api/library/ingest`（multipart，files 字段）、`GET /api/library/jobs/{id}`
  （进度快照：state/phase/total/done/failed/current/items/error）、
  `POST /api/library/jobs/{id}/cancel`（协作取消）、`POST /api/library/rebuild`
  （confirm 标记，缺省 422 `rebuild_confirm_required`）。新增稳定错误码 4 个
  （library_job_busy / library_job_not_running / job_not_found /
  rebuild_confirm_required），全部落在既有 404/409/422 状态类。OpenAPI 快照经
  `python -m siku.api.contract --refresh` 刷新，diff 仅含本 change 的 5 个新路径。
- **决议 #2（文件交接）**：浏览器 file picker 上传字节流（multipart）。裁决关键事实：
  桌面壳主窗口加载 sidecar 同源页且**设计上无 IPC 权限**（desktop-shell 归档件的
  capability 描述明示），路径桥接需给远程源开 IPC + dialog 插件，正是壳变更刻意
  回避的权限面扩大。字节经 localhost HTTP 直达内核，webview 不解析不处理；
  红线 2 与 ADR-0001 的实质（语料不经 invoke/事件、业务逻辑不进壳）均满足。
  幂等经确定性暂存路径（`$TMPDIR/siku-uploads/<sha256前12>/<原文件名>`）保真：
  同内容同名重导入 → 同 source_id → 既有管线 skip。
- **决议 #3（任务生命周期）**：单任务槽（进程内 daemon 线程，ingest 与 rebuild
  互斥 409）；失败仅在任务结果中呈现、不落第二份元数据；协作式文件粒度取消
  （当前文件完成后停止，已完成部分保留，取消后不衔接索引；索引阶段不可中断）；
  进程重启 = 内存态消失，重跑按 source_hash 幂等续传。

## 红线与 spec 符合性

- **红线 2（UI↔内核只经 HTTP）**：导入/进度/取消/重建全部经新增端点；UI 无任何
  直连文件系统的路径（LibraryView.tsx 仅调 api.ts 的 fetch 封装）。
- **红线 3（语料唯一事实源）**：清单全部只读派生（attachments 原件 hash +
  notes frontmatter + 索引 manifest），不写任何文件——
  `test_library_listing_is_read_only` 以 mtime/size 快照断言两次 GET 零写入。
- **红线 1（本地优先）**：不引入任何新外部依赖行为；上传与索引均在本机闭环。
- **索引衔接语义**：仅当 items 存在 created/updated 时自动增量索引；embedding
  未配置或模型身份不匹配 → 任务 failed + 既有 `map_domain_error` 中文指引（与设置
  中心告警同一出口，`test_index_failure_fails_job_with_existing_guidance`）。
- **依赖纪律**：仅新增 `python-multipart`（FastAPI 文件上传官方必需件，纯解析
  轻依赖），符合红线 4 轻量安装。

## 测试证据

- pytest 全量 **546 passed**（基线 533 + 本 change 新增 13）；ruff check/format、
  mypy、pre-commit、openspec strict（changes 2/2 + specs 7/7）、npm lint/test/build
  （19 tests）全绿。
- 契约测试覆盖：清单四态/三态枚举与同源派生、只读性、进度单调性与 0/N→N/N、
  同 source_hash 重跑 skip、白名单外忽略（不落盘不出清单）、重复触发 409（含
  rebuild 互斥）、协作取消（当前文件完成后停止、done<total、暂存清理、不衔接索引）、
  未知 job 404、取消已结束任务 409、内存态随进程消失 + 重启后幂等重跑、重建确认
  422/执行、索引失败转任务失败且不漏英文异常细节、上传文件名路径穿越清洗。
- spec delta 补充一处：tasks.md 决议 #3 要求取消语义落地，故在「提供导入摄取任务
  与进度查询」requirement 下增补取消场景（归档时随 deltas 同步入主 spec）。

## 手工冒烟记录（2026-09-19，serve + 假 BYOK 端点）

本机无真实模型端点（无 Ollama/云端 key），以 openai 兼容 mock（/embeddings +
/chat/completions，确定性向量）替代模型通道，`siku serve` 真实进程 + curl 全链路：

1. **空清单**：`GET /api/library` → `{"sources":[]}`（UI 空状态引导路径）。
2. **导入**：multipart 上传 2 个 Markdown → job `running total=2` → 轮询推进至
   `succeeded`，items 两笔 `created`，暂存文件用毕即删。
3. **清单刷新**：两来源 `ingested`；首次无 embedding 时索引阶段任务 failed 且
   error 为既有 BYOK 配置指引（诚实降级路径）✓。
4. **重建确认语义**：不带 confirm → 422 `rebuild_confirm_required`；带 confirm →
   任务执行。
5. **全链路**：接入 mock embedding 后导入第三份语料 → 任务 `succeeded`
   （摄取 + 自动增量索引）→ 清单三来源全部 `indexed` → `POST /api/search` 与
   `POST /api/ask` 均命中新语料（ask retrieval result_count=3，LLM 通道真实往返）→
   确认全量重建 `succeeded` → 重建后检索仍命中（result_count=3）。

**遗留（触发型，与 HANDOFF 台账一致）**：Tauri 壳内真实端点的界面级点击冒烟
（导入按钮/进度条/确认对话框在 webview 中的实机表现）等真实 BYOK 环境一并执行；
本 change 的 UI 行为已由 19 项 vitest（jsdom）覆盖。
