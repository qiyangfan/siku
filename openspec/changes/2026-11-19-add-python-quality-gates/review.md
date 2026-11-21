# 评审记录：2026-11-19-add-python-quality-gates

> apply 阶段实现证据（2026-11-19）；尚未提交/推送，CI 未绿，按纪律保持 active、不归档。

## 门禁与基线

| 项 | 基线 | 落地后 |
|---|---|---|
| ruff `C901`/`PLR0912`/`PLR0915`（默认 10/12/50） | C901 16、PLR0912 7、PLR0915 8（共 31 处/24 文件） | `uv run ruff check .` 0（359 文件） |
| pylint `too-many-lines`（1000） | `cli.py` 1239、`api/app.py` 1158 | 0 命中 |
| pylint `too-many-return-statements`（6） | 2 处 | 0（`map_ask_error` 改表驱动、注册端合并 409 分支） |
| pylint `too-many-instance-attributes`（7） | 8 处 | 0（报告/任务/计划/检索模型按语义分组） |
| pylint `too-many-public-methods`（20） | 0（src）；tests 1 处（`TestGetSettings` 21） | 0（拆出 `TestLlmEnvFallback`） |
| 测试模块体积 | `tests/test_api_settings.py` 1081 行 | 拆为 789 + 233 行两模块，共享夹具入 `settings_helpers.py` / `tests/conftest.py` |
| import-linter 边界契约 | 无 | 3 contracts kept（extractors 独立、内核不反向依赖入口/同步、retrieve 不依赖 ingest/sync） |
| ruff `PERF`/`RET`/`TID`/`ICN`/`PLR0402` | 5 处（PERF401×3、RET504×1、ICN001×1） | 0 |
| 超长行 E501（100）/ import 排序 I | 已启用 | 保持，全绿 |

未启用项（design.md D1b 有逐项实测存量）：pylint `too-many-locals` 18、
`too-many-arguments` 21；PLR2004 329；duplicate-code 17 块。均为规则集取舍，参数无一
改动、无 warn 降级。`too-many-return-statements` 与 `too-many-instance-attributes`
已在本 change 第二批启用（见下节）；ruff `S` 在 `2026-11-19-add-codeql` 批次启用，
测试目录按其测试惯用规则放行，生产误报逐条带原因 noqa——两者都不在本 change 的
「零豁免」口径内。

## 拆分清单

- 热点函数 12 处：`sync_index`(22/91)、`evaluate_retrieval`(16/76)、`ingest_path`(15/59)、
  `load_golden_set`(14)、`plan_source`(14)、`_run_plan`(12)、`map_probe_error`(12)、
  `_extract_content`(12)、`scan`(11)、`plan_join`(11)、`_parse_frontmatter`(11)、
  `stage_index_reduction`(11/60)；另 `build_library_view`(16)、`map_domain_error`(46)、
  `scripts/smoke_clean_env.py` 两处、两个测试热点。拆分只做提取函数/提前返回，
  异常类型、文案、日志字段、返回结构原样。
- 模块拆分：`cli.py`(1335) → `siku/cli/` 包（app/core/commands/* + `__main__.py`），
  入口 `siku.cli:app` 与 `python -m siku.cli` 均保持；`api/app.py`(1158) → 702 行，
  路由组拆到 `api/routes_library.py`(410)、`api/routes_graph_wiki.py`，公共响应/锁口径
  抽到 `api/http_help.py`。注册函数按路由组二次拆分，每个都在默认阈值内。

## 行为等价证据

- 子代理对 settings/providers/notes_reader 三文件在临时 worktree 跑 HEAD 对照：
  全量失败集合逐行一致（均为 `NO_PROXY=[::1]` 引起的 `httpx.InvalidURL` 环境噪声）。
  `map_probe_error` 另做旧/新逐异常差分（3 通道 × 4 协议 × 全错误类）零差异。
- `map_domain_error` 按错误族查表拆分，保持 isinstance 顺序；专项等价脚本对全部
  错误类型 × 通道 × surface 比对 `(status_code, code, message)` 零差异。
- OpenAPI 快照：路由注册顺序按 HEAD 恢复（`/api/ingest` 在资料库路由之前），
  `tests/test_api.py::test_openapi_snapshot_has_no_drift` 通过。
- 全量测试：`env -u DASHSCOPE_API_KEY -u NO_PROXY -u no_proxy pytest` →
  **887 passed，EXIT=0**（默认排除 e2e）。仓内 CWD 直跑时 `data/graph` 残留会让
  `test_graph_api_and_cli_json_fields_are_identical` 多出一行全量重抽告警，
  换干净 CWD 即过——环境噪声，非回归。
- 两进程写锁测试：原 3s 持锁期相对"2s 锁超时 + CLI 启动"只有约 1s 余量，属固有竞态；
  拆分后 CLI 启动约 1.9s 使其稳定失败。修复只动测试夹具（持锁 10s + 显式 terminate），
  断言不变；单独连跑 5/5 通过。
- 设置测试拆分属纯搬运：测试名、断言与夹具语义不变，拆分后设置相关 62 个测试全绿，
  全量仍为 887 passed。

## 负向验收（逐类，实际输出）

1. 复杂度：临时 `src/siku/_gate_probe.py`（10 个 if）→
   `C901 'probe' is too complex (11 > 10)`，退出 **1**；移除后回 0。
2. 模块体积：临时 1009 行模块 → `C0302: Too many lines in module (1009/1000)`，
   pylint 退出 **16**；移除后 10.00/10。
3. import 边界：`siku/extractors/_boundary_probe.py` 引入 `from siku.api.app import ...` →
   `抽取器不依赖其他内核模块 ... BROKEN`、`Contracts: 2 kept, 1 broken`，退出 **1**；
   移除后 `3 kept, 0 broken`、退出 0。
4. 新增规则束：探针同时含 append 循环（PERF401）、多余赋值（RET504）、
   `import pyarrow`（ICN001）、`..` 相对导入（TID252）、`import x.y as y`（PLR0402）→
   ruff 逐条命中、退出 **1**；移除后 `All checks passed!`、退出 0。

## R09xx 第二批（默认参数，零豁免）

- `too-many-instance-attributes` 8→0：`GraphHealthReport`(11→4: identity/counts/calls/
  warnings)、`_Job`(11→7: progress/result)、`LibraryJobManager`(15→7: targets/runners)、
  `SourcePlan`(9→4: actions)、`ChunkRecord`(8→5: citation)、`SearchResult`(10→7:
  citation)、`CaseResult`(10→7: metrics)、`ApiEmbeddingProvider`(8→7: 去掉重复的
  `_base_url`)。JSON 契约保持扁平：CLI `--json`、`/api/search`、MCP search/entity-join
  各自显式摊平 citation；OpenAPI 快照与既有 JSON 测试全绿。
- `too-many-return-statements` 2→0：`map_ask_error` 改优先级表（子类在前），
  `library_sources_create` 合并两个 409 分支。
- `api/library.py` 997 行已贴 1000 上限，只读清单拆到 `api/library_view.py`
  （`AttachmentDigestCache`/`build_library_view` 的导入同步到新模块）。
- 不启用 `too-many-locals`/`too-many-arguments`/`too-many-positional-arguments`：
  实测 pylint 把参数计入 locals（16 参函数即报 16/15）；`serve` 声明 18 个 CLI
  选项，8 个 typer 命令参数 6~18 个。整条启用只能改 CLI 契约或隐藏参数，故保持关闭；
  内部 14 处参数/13 处 locals 可拆但拆完仍被 CLI 面卡死，不做无门禁的碎片化。
  `too-few-public-methods` 54 处为协议单方法实现/数据载体/单测试类，PMD 无对应维度。

## 遗留（未闭环）

- 未提交、未推送；CI 未执行（账号级账单锁定，见 HANDOFF）。
- 分支保护 required 仍未设（同上原因）。
- UI 侧复杂度/行数门禁已在 `2026-11-19-add-web-quality-gates` 落地：
  ESLint `complexity` 取工具默认 20、`max-lines` 1000，7 处热点全部重构到阈值内；
  本批当时不开 warn 的判断保持不变。
- 本机已知 flaky：`test_two_process_mutex_via_subprocess`（HEAD 既有，负载高时偶红）。

## 归档前清单

- [x] 独立评审（2026-11-21，本地复核，发现并修复 1 处回归，见文末）
- [ ] 提交/推送后 CI 全绿（含 pylint / lint-imports 两步）——阻塞于账号级 Actions 锁定
- [ ] `security / secrets` 与测试 job 设为 required——同上

## 独立评审（2026-11-21）

按 CI 同命令本地实跑结构门禁与依赖边界：

| 检查 | 结果 |
|---|---|
| `pylint --disable=all --enable=too-many-lines,too-many-public-methods,too-many-return-statements,too-many-instance-attributes src/siku tests scripts benchmarks` | 修复后 0 条、退出 0 |
| `pylint --jobs=0 src/siku scripts`（W/E） | 10.00/10 |
| `lint-imports` | 3 contracts kept |
| `ruff check .` / `mypy` | 0 / 156 文件 0 issue |

**发现并已修复**：`67d052c`（本 change 之后）为 `SqliteIndex` 追加了公开
`connection` property，使 `src/siku/retrieve/store.py` 的公开方法数升到 21/20，
本 change 声称的「too-many-public-methods 0（src）」在 HEAD 上不再成立。因 CI 未跑，
该回归此前无人发现。

修复方式取最小面：删除该 property，`copy_sources_from` 在类内直接用
`source._connection`；基准脚本改为在计时段内 `checkpoint_and_close()`
（提交与 WAL 截断本就属写入成本）。修复后上述门禁全绿，`test_retrieve_store.py`
等 8 个相关套件通过。CI 全绿与 required 仍待外部条件。
