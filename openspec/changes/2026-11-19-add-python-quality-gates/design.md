# 设计：结构质量门禁的规则选型与拆分策略

## Context

见 proposal.md「Why」。参考取两处：`kongming`（同栈 Python + React，ruff
`C901`/`PLR0912`/`PLR0915` + pylint 体积两条，默认阈值）与 `workspace/java`（PMD 7 官方
类别选集 + Checkstyle LineLength 120 的"主流默认"取向）。本仓基线：复杂度类 54 处、
`cli.py` 1239 行、`api/app.py` 1158 行。

## Goals / Non-Goals

- 目标：结构劣化可被 CI 阻断，且规则/参数可解释（全部为工具默认值）。
- 不做：见 proposal.md「Non-goals」。设计层另外排除——不为过闸调高阈值、不给测试
  目录开 per-file 豁免、不把规则降级为 warn。

## Decisions

### D1 规则集合取 kongming 同口径（默认阈值）

- ruff：`C901`（max-complexity 10）、`PLR0912`（max-branches 12）、`PLR0915`
  （max-statements 50）。E501（100）与 I 已启用。
- ruff 补充默认规则集：`PERF`（性能反模式）、`RET`（返回卫生）、`ICN`（约定别名）、
  `TID`（父级相对导入，默认只禁 `..` 形式）、`PLR0402`（子模块别名导入须改 from）。
- pylint：`--disable=all --enable=too-many-lines,too-many-public-methods`
  （默认 1000 行 / 20 个公有方法），扫描面为 `src/siku tests scripts benchmarks`
  ——体积门禁不区分生产/测试/脚本，否则 tests/ 会成为无闸区。ruff 的对应规则
  （PLR0904）仍在 preview，不用 preview 规则换取"单一工具"的形式统一。

### D1b PMD 等价维度的实测覆盖与规则集取舍

逐条跑过参考仓 PMD/Checkstyle 对应的 Python 等价物，未启用项均为规则集取舍，
不是豁免：没有任何 per-file ignore、noqa、阈值上调或 warn 降级。

| 维度 | 启用项 | 未启用项实测存量与取舍 |
|---|---|---|
| 圈复杂度 | C901 10 | —（PMD 的 Cognitive/NPath 无 Python 主流等价物，参考仓亦排除） |
| 上帝方法 | PLR0912 12、PLR0915 50、pylint `too-many-return-statements` 6 | `too-many-locals` 23 处与 `too-many-arguments` 22 处、`too-many-positional-arguments` 11 处不启用：pylint 把参数计入局部变量，8 个 typer 命令声明 6~18 个选项（`serve` 18 个），任何满足默认阈值的做法都只剩改 CLI 契约或隐藏参数两条路；已清 5 处非 CLI 存量（graph/wiki/library）后停止继续拆分，避免无门禁的碎片化 |
| 上帝类 | 源文件 1000 行、公有方法 20、pylint `too-many-instance-attributes` 7 | `too-few-public-methods` 54 处（Extractor 协议单方法实现、数据载体、pytest 单测试类；PMD 无对应维度） |
| 魔法数 | — | PLR2004 329 处（多为 HTTP 状态码与测试数据；参考仓 Checkstyle 亦按注解忽略） |
| 重复代码 | — | pylint duplicate-code 17 块（参考仓未启用 CPD） |
| import 卫生 | I、F401/F403（F）、TID、ICN、PLR0402、import-linter 三契约 | PLC0415 104 处（惰性导入是规避重依赖/循环依赖的手段） |
| 安全 | secret scanning（独立 job） | ruff `S` 已在 `2026-11-19-add-codeql` 批次启用：`tests/**` 放行测试惯用规则，生产 8 处 assert 改显式 raise，其余经核实误报逐条 `# noqa`（带原因）；本批不重复 |
| 超长行 | E501 100 | — |

R09xx 的实测结论（全部取 pylint 4.1.4 默认参数，扫描 `src/siku tests scripts benchmarks`）：

- `too-many-return-statements`(6) 2 处 → 改表驱动/合并异常分支，已启用。
- `too-many-instance-attributes`(7) 8 处 → `GraphHealthReport`(11→4)、`_Job`(11→7)、
  `LibraryJobManager`(15→7)、`SourcePlan`(9→4)、`ChunkRecord`(8→5)、
  `SearchResult`(10→7)、`CaseResult`(10→7)、`ApiEmbeddingProvider`(8→7)，已启用。
  `api/library.py` 拆分只读清单到 `api/library_view.py`，同时守住 1000 行上限。
- `too-many-locals`/`too-many-arguments`/`too-many-positional-arguments` 不启用：
  实测 pylint 把函数参数计入 locals（16 参函数报 16/15）。`serve` 声明 18 个 CLI
  选项，`ingest index` 8、`graph` 8+6、`retrieve` 13+13+12、`scan` 7；要整条启用，
  只能删/合并 CLI 选项（产品契约变更）或用 click/Context 把参数藏起来（指标游戏）。
  内部函数的 14 处参数与 13 处 locals 可拆，但拆完仍被 CLI 面卡死，故不做无效改动。
- `too-many-branches`/`too-many-statements` 与 ruff `PLR0912`/`PLR0915` 同阈值且已为 0，
  不重复启用；`too-many-ancestors`/`too-many-boolean-expressions` 零命中。

### D2 顺序：先拆热点，再开闸

基线违规集中在 12 个函数（`indexer.sync_index` 22 复杂度/91 语句、
`cli.evaluate_retrieval` 16/76、`ingest_path` 15/59、`load_golden_set` 14、
`plan_source` 14 等）。先按"单一职责"拆这些函数并跑对应测试，再落地配置；避免为了
让数字下降做无意义碎片化。拆分只做提取函数与提前返回，不改异常/日志/返回值。

### D3 模块体积：拆包/拆路由，公开入口不变

- `cli.py` → `siku/cli/` 包（app/core/commands/*），`siku.cli:app` 入口不变；
  测试的 monkeypatch 目标同步改到新模块（属机械同步，不改断言语义）。
- `api/app.py` → 抽出 `routes_library.py`、`routes_graph_wiki.py`，各自暴露
  `register_*_routes(application, **deps)`；闭包依赖显式传参，路由装饰器与
  response_model 原样搬迁。拆出的注册函数若自身超限，继续按路由组二次拆分。

### D4 import 边界用 forbidden 契约（不用分层）

`retrieve ↔ graph` 存在既有合法双向依赖（实体锚点/统计），layers 契约无法表达；
改用 forbidden 精确表达红线："底层不反向依赖入口层"：

- `siku.extractors` 不依赖任何其他 `siku.*`（ADR-0005 可插拔边界）。
- `siku.retrieve`/`siku.graph`/`siku.wiki`/`siku.qa`/`siku.model_supply`/`siku.ingest`
  不依赖 `siku.api`/`siku.cli`/`siku.mcp`/`siku.sync`/`siku.sidecar`。

### D5 CI 落点与执行次数

pylint 与 `lint-imports` 加入现有 `test` job 的 3.12 桶（矩阵两版本只跑一次），
ruff 两版本照跑；全部 exit 非 0 即阻断，不留 `continue-on-error`。前端本批不动。

### D6 本地验证注意

本机 `NO_PROXY` 含 `[::1]`，httpx 会抛 `InvalidURL: Invalid port`，导致 provider 类
测试假红。验证与 CI 等价命令时用 `env -u NO_PROXY -u no_proxy`；这是环境噪声，
不写进门禁、不做代码兼容。

## Risks / Trade-offs

- [拆分改变行为] → 每个热点拆分后跑映射测试；`map_domain_error` 用"旧实现逐异常对比"
  的等价性脚本自证。
- [拆包后 monkeypatch 失效] → 同步更新测试目标并全量 pytest 对照 HEAD 失败集合。
- [契约误报] → 契约只列实际依赖方向成立的 forbidden 规则；新增反向依赖时先改设计。
- [门禁太紧拖慢迭代] → 阈值全部默认、无增量容忍；确实需要例外时走 ADR 评审，
  不在配置里加豁免。

## Migration Plan

无数据/接口迁移。回滚 = 还原 pyproject 的 ruff/importlinter 配置与 CI 两步；
代码拆分可独立保留。

## Open Questions

无。
