# 评审记录：add-graph-auto-refresh

## 实现范围

- **开关存储与读写**：`sync/registry.py` 新增 `graph_auto_refresh` 库级设置
  （`sync_settings` 表，缺省关，损坏值回退缺省）；`api/models.py` 扫描设置响应/
  请求扩字段（部分更新语义，旧客户端兼容）；`api/app.py` 端点读写；契约快照刷新。
- **抽取身份闸门**：`graph/cache.py` `cache_meta` 增身份记录读写；
  `graph/service.py` 构建成功落盘后记录 (extractor_id, model_id, prompt_version)，
  失败不落；`graph/refresh.py` 身份比对与 `full_reextract_warning` 预告。
- **收尾链与策略**：`graph/refresh.py` 新增 `maybe_refresh_graph`（决策顺序：
  开关 → 快照存在 → 通道可解析 → 身份一致 → 执行，跳过均带稳定码 + 中文文案）与
  共享 `llm_extractor_factory`；`api/library.py` 任务收尾链索引后衔接（注入
  runner，非 rebuild、未取消才触发；失败只落通知不改终态）；`api/app.py` 接线；
  `cli.py` `siku scan` 同口径收尾（图谱刷新异常本地兜底，不把已成功扫描判失败）。
- **通知与 UI**：`LibraryJobResponse.notice` 可选字段；`ui/src/api.ts` 类型与
  部分更新；`ui/src/LibraryView.tsx` 扫描间隔旁开关 + 中文说明 + 任务通知展示。
- **顺带修复（既有类型告警，均在本 change 触及文件内）**：`api/app.py` 两处
  工厂 Optional 收窄（assert，同 library.py 既有惯例）；`sync/service.py`
  staged/report 不变量收窄；`api/library.py` `bool()` 包裹导致 pyright 不收窄；
  `cli.py` 三处——`_retrieval_error_message` 收窄为 RetrievalError、`report`
  精确初始化与守卫、`_CliScanObserver` 补 `ops` 清单（修 `siku remove --json`
  的 AttributeError 潜在崩溃）。

## 验证证据（2026-10-17，本机）

- 全量 pytest：**862 passed, 1 skipped**（基线 830 + 本 change 净增 32）。
  命令：`env -u DASHSCOPE_API_KEY uv run python -m pytest -o addopts=""`（本机口径，
  见 HANDOFF）。
- ruff：`ruff check src/ tests/` All checks passed；`ruff format --check`
  119 files already formatted。
- OpenSpec：`openspec validate add-graph-auto-refresh --changes --strict` 通过。
- UI 门禁（`ui/` 内，本机曾缺 node_modules，已按 package-lock.json `npm ci` 恢复）：
  `tsc --noEmit` exit 0；`eslint src --max-warnings 0` exit 0；
  `vitest run` **133 passed**（基线 131 + 新增 2）；`vite build` exit 0。
- 契约：`contracts/openapi.json` 刷新，diff 仅本件新增字段
  （`graph_auto_refresh` 与 `notice`）；快照漂移测试通过。
- 关键行为冒烟（测试级）：
  - 决策表 6 分支全绿（disabled/graph_missing/identity_changed/
    identity_unknown/channel_unavailable/refreshed），工厂调用时机断言；
  - 增量计数：新文档 1 chunk 走 LLM、旧 2 chunk 全缓存命中；
  - 失败隔离：抽取失败 → 旧 parquet 原样可读、身份记录不回退；
  - 任务链：开关开+就绪 → 通知含计数；取消/rebuild → 不触发；runner 抛错 →
    摄取仍 succeeded + 失败通知；
  - 幂等闸门扩展：自动刷新产物 vs 干净目录显式全量构建产物 **diff 为空**；
  - CLI 预告：换模型后 stderr 出「全量重抽 2 个 chunk」，stdout 仍为纯净 JSON。

## 评审循环

**第 1 轮（实现过程自查，发现并修复）**：

| 问题 | 修复 |
|---|---|
| CLI scan 图谱刷新异常穿外层 except 把扫描判失败（违反「刷新失败不改变终态」） | 图谱调用局部 try/except 兜底为中文通知 |
| rebuild 任务仍触发图谱维护（漏排除条件） | `_finish_with_index` 加 `if not rebuild` |
| `identity_unknown`（升级路径：快照在、身份记录无）与 `identity_changed` 混同一文案 | 拆两个稳定码与诚实文案 |
| 测试文件 `b"…中文".encode()` 语法错误、E501、未用变量、缺注解 | 逐项修正 |
| `updateScanSettings` 改对象参数后漏改 `saveInterval` 调用 | 补 `{ interval_secs: parsed }` |
| Mantine Switch 查询用错 role | 改 `getByLabelText` |

**第 2 轮（独立子代理评审）**：待补（本轮为清单执行模式一次性完成，未启动独立
子代理评审；归档前如需可补）。

## 边界核对（归档前逐项确认）

- [x] 自动路径不创建图谱、不重建失效快照、不生成 wiki（decision table +
      graph_missing 分支断言）
- [x] MCP `ingest` 与 CLI `siku ingest` 不触发自动维护（未接线，无回归面；
      既有两入口连索引都不维护，另案）
- [x] 抽取失败不改变摄取/扫描成功终态，旧快照可读（失败隔离测试）
- [x] 取消与 rebuild 任务不触发自动维护（两条专项测试）
- [x] 自动产物与显式产物 diff 为空（幂等测试扩展）

## 工具链备注（非代码问题）

pi-lens 自动检查本会话多次报出 `siku.graph.refresh` 导入无法解析等阻塞，
经权威工具（`uv run pyright` 同款 1.1.414、运行时导入、隔离导入、相关测试
全过）反复复证为检查器缓存滞后（其模块索引早于 `refresh.py` 创建）；最终
自行降级为 stale advisory。另有 `ui/node_modules` 缺失导致真实门禁无法运行，
已按 package-lock.json `npm ci` 恢复（esbuild postinstall 被 allowScripts
策略阻止，不影响 tsc/eslint/vitest/build）。
