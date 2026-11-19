# 提案：Python 结构质量门禁——复杂度、上帝类/上帝方法、模块体积、import 边界

## Why

本仓门禁只看"能不能跑"（ruff 基础规则、测试、构建），不看结构劣化：基线实测
16 处圈复杂度超标（最重 `sync_index` 22、`evaluate_retrieval` 16、`ingest_path` 15）、
7 处分支超标、8 处语句超标，`cli.py` 1239 行、`api/app.py` 1158 行。这些正是 PMD
在 Java 侧拦的"上帝方法/上帝类/圈复杂度"，Python 侧此前无对应闸门，劣化无信号。

## What Changes

- **规则（全部取工具默认参数）**：
  - ruff select 增加 `C901`（圈复杂度 10）、`PLR0912`（分支 12）、`PLR0915`（语句 50）——
    与 kongming 同口径；E501 超长行（100）与 I（import 排序）已在。
  - ruff 追加默认规则集 `PERF`/`RET`/`ICN`/`TID`/`PLR0402`（性能、返回卫生、别名与
    相对导入），与上述结构规则同批开闸。
  - pylint 开 `too-many-lines`（1000）、`too-many-public-methods`（20）、
    `too-many-return-statements`（6）、`too-many-instance-attributes`（7）四条，
    ruff 无稳定等价规则（kongming 同口径）；扫描面覆盖 `src/siku tests scripts benchmarks`。
  - 修掉返回数 2 处、属性数 8 处存量：报告/任务/计划/检索模型按语义分组
    （identity/counts/calls、progress/result、actions、citation 等），并把
    `api/library.py` 的只读清单拆到 `api/library_view.py`，守住 1000 行上限。
  - import-linter 增加 forbidden 契约：入口层（api/cli/mcp/sync）不得被底层
    （extractors/ingest/retrieve/graph/wiki/qa/model_supply）反向依赖。
- **先拆热点再开闸**：12 处 src 热点函数拆成单一职责的小函数；`cli.py` 拆为
  `siku/cli/` 包、`api/app.py` 的路由组拆到 `api/routes_*.py`，全部保持公开入口与
  行为不变。零 `noqa`/零豁免。
- **CI 落点**：`ci.yml` 的测试 job 在 ruff 后追加 pylint 与 `lint-imports`
  （单版本执行，避免矩阵重复）；既有 ruff 步骤自动覆盖新增规则。

## 受影响决策

只引用、不修改：ADR-0008（CI 版本矩阵——门禁加入既有测试 job，不引入新 Action）。
本件不改变任何产品行为，`skip_specs: true`。

## Impact

文件面：`pyproject.toml`（ruff select、dev 依赖 pylint/import-linter、importlinter 契约）、
`.github/workflows/ci.yml`、`src/siku/cli.py`→`src/siku/cli/`、`src/siku/api/app.py`
与新增 `api/routes_*.py`、若干热点函数拆分。零运行时行为变化；测试断言不改语义。

## Non-goals（不做清单）

- 不开 mypy / pyright / 覆盖率阈值（handoff P1 的独立项，另行排期）。
- 不开 UI 侧复杂度/行数门禁：实测 30 处存量（`WikiView` 复杂度 35、`api.ts` 534 行），
  按 handoff 批次 8（P1 Web）统一处理，不在本批用 warn 冒充门禁。
- 不开 pylint `too-many-arguments`(5)/`too-many-positional-arguments`(5)/
  `too-many-locals`(15)：pylint 把参数同时计入局部变量，`siku serve` 声明 18 个 CLI
  选项、另 7 个 typer 命令参数 6~13 个；整条启用只能改 CLI 契约或把参数藏进
  click/Context，故不启用（实测见 design.md D1b）。
- 不开 `too-few-public-methods`(2)：54 处命中全部是 Extractor 协议单方法实现、
  数据载体与 pytest 单测试类，PMD 无对应维度。
- PLR2004 329 处（多为 HTTP 状态码与测试数据；参考仓 Checkstyle 按注解忽略）；
  pylint `too-many-branches`/`too-many-statements` 与 ruff PLR0912/PLR0915 同阈值重复，
  不重复启用。
- 不做依赖漏洞/secret/CodeQL/SBOM（已在或另批）；不改 Rust clippy 与 UI lint 既有参数。
- 不引入豁免、不调高任何阈值、不把违规改成 `warn`。
