# 评审记录：治理文件进 CI

## 验证证据（本机实测）

| 项 | 结果 |
|---|---|
| `openspec validate --all --strict` | 18 passed / 0 failed（含本批 6 个 change） |
| `actionlint`（ci/security/codeql） | 通过 |
| ci.yml governance job 语法 | actionlint 通过 |

## 保留判断（明确不引入）

- **commitlint**：Python 优先仓库，无根 Node 工具链；提交规范由 AGENTS.md 与人工
  评审执行，为一条规则引入根 package.json/node_modules 不成比例。
- **markdownlint / taplo / yamllint**：中文技术散文格式规则只会制造 churn；
  YAML/TOML 结构已由 pre-commit `check-yaml`/`check-toml` 与 actionlint 覆盖。

## 遗留

- 外部 CI 未绿（账号账单锁定）；解锁后确认 governance job 首跑。
