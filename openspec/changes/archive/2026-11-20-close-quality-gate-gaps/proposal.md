# 提案：文档 lint 与链接门禁收口

## Why

门禁体系里独缺文档面：`openspec/AGENTS.md` 与 `docs/adr/` 是行为与决策的唯一权威口径，
但 Markdown 结构（标题、代码围栏、列表、行宽）没有任何机器校验；相对链接过去只在
`tests/test_docs_links.py` 里校验路径存在性，且**从不校验锚点**——标题改名或跳转的
`#锚点` 失效不会被发现。`2026-11-19-add-ci-governance` 曾以「中文散文格式规则只会
制造 churn」为由不引入 markdownlint，本轮先实测存量，确认可修后再接闸。

## What Changes

1. **markdownlint-cli2 0.24.1**：新增 `.markdownlint-cli2.jsonc`，只守护人写文档
   （`README.md`/`AGENTS.md`/`docs/**`/`benchmarks/README.md`/`ui/README.md`）；
   中文行宽 120、代码块与表格行豁免；表格对齐规则（MD060）全局关闭并写明理由。
   存量逐条处置：修 12 处超宽长段、3 处无语言围栏、ROADMAP 6 处列表符号与
   3 处序号；`ui/design-system/MASTER.md` 以行内指令按文件登记 MD013 豁免
   （表内 token 路径无法折行，理由见 design.md D4）。
2. **相对链接 + 锚点检查脚本**：`scripts/check_md_links.py`，零网络；校验相对路径、
   目录链接、百分号编码、目标文件标题锚点（GitHub slug 规则、同名去重、HTML id/name、
   `{#id}` 显式锚点）。扫描面为 docs/openspec/benchmarks/ui/src/scripts 全量 md。
   `tests/test_docs_links.py` 由「全仓路径断言」改为解析器单测，全仓扫描归脚本。
3. **接入 pre-commit 与 CI governance**：两个 hook（`markdownlint`、`markdown-links`）
   与 CI governance job 同命令，本地即拦。
4. **门禁实测**：markdownlint 22 文件 0 问题；链接检查 257 文件 0 坏链；ruff/mypy/
   pytest 全绿（903 passed，覆盖率 90.03%）。

## 明确不做（有理由，不是遗漏）

- **Rust CodeQL**：GitHub CodeQL 无 Rust 语言支持；桌面壳由 clippy pedantic（build
  mode 下数据流类告警）+ rustdoc `-D warnings` + cargo-audit（RUSTSEC 公告）+
  cargo-deny（许可证/来源）覆盖，`codeql.yml` 头注释已登记该替代，见 tasks 6.2。
- **openspec/ 纳入 markdownlint**：change/spec 结构由 `openspec validate --strict` 权威校验；
  归档件是历史快照，用新 lint 回溯整改会让归档件与当时的评审证据脱节。
- **MD060 全仓整改**：157 行表格需要按 CJK 显示宽度补齐竖线，纯美观收益，不做。
- **`ui/design-system/MASTER.md` 保持行内豁免而非改写**：其 token 表一行记录一组
  「用途/token/取值」，token 列是完整 CSS 变量族路径，折行会拆散三元组；
  文件已脱离 globs，行内指令作为「将来纳入即生效」的登记。

## 受影响决策

只引用、不修改 ADR-0008（门禁沿用既有 governance job，不新增矩阵桶）。`skip_specs: true`。

## Impact

- 新增：`.markdownlint-cli2.jsonc`、`scripts/check_md_links.py`。
- 修改：`.pre-commit-config.yaml`、`.github/workflows/ci.yml`（governance job）、
  `tests/test_docs_links.py`（改为单测）、README/docs 的格式修复。
- 零运行时变化；文档面改动在提交与 CI 时被校验。

## Non-goals

- 不引入 commitlint / taplo / yamllint（YAML/TOML 结构已由 check-yaml/check-toml 与
  actionlint 覆盖）。
- 不做外链可达性检查（需网络、受网络波动影响，门禁禁止网络依赖）。
- 不校验 reStructuredText/HTML 文档（仓库无此类文档）。
