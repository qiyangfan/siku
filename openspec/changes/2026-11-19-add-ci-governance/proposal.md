# 提案：治理文件进 CI——OpenSpec 严格校验 + actionlint

## Why

治理文件此前只在本地手工执行：`openspec validate --strict` 靠自觉，工作流 YAML
没有语法门禁（actionlint 只在提交时手工跑）。这两类漂移不会被任何 CI 步骤发现，
是门禁体系自身的盲区。

## What Changes

- `ci.yml` 新增独立 `governance` job（不受路径门控影响）：
  - `npx --yes @fission-ai/openspec@1.17.0 validate --all --strict`
  - 下载 actionlint 1.7.12 并检查全部 workflow。
- 本机实测：`openspec validate --all --strict` 16 项通过；actionlint 全绿。

## 明确不引入（有理由，不是遗漏）

- **commitlint**：本仓是 Python 优先仓库，无根 Node 工具链；提交规范由
  `AGENTS.md` + 人工评审执行。为一条规则引入根 package.json/node_modules 不成比例。
- **markdownlint / taplo / yamllint**：文档以中文技术散文为主，格式类规则只会制造
  churn；YAML 结构由 pre-commit `check-yaml` 与 actionlint（workflow）覆盖，
  TOML 由 `check-toml` 覆盖，JSON 由 prettier（ui/）与解析器覆盖。

## 受影响决策

只引用、不修改 ADR-0008。`skip_specs: true`。

## Impact

文件面：`.github/workflows/ci.yml`。零运行时变化；每次 push/PR 校验治理文件。

## Non-goals

- 不引入 commitlint/markdownlint/taplo（理由见上，后续如需再单独立项）。
- 不把 `--archived` 校验加入 CI（归档 change 的 tasks 清零以归档评审为准）。
