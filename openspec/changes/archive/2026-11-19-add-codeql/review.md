# 评审记录：CodeQL + ruff S

## 验证证据（本机实测）

| 项 | 结果 |
|---|---|
| `actionlint`（codeql.yml / 全 workflow） | 通过 |
| `ruff check .` | 0（S 全族启用后） |
| ruff `S602` 探针 | `subprocess.run(user_input, shell=True)` → 退出 1；移除后 0 |
| 全量 pytest | 887 passed（断言改 raise 后） |
| openspec strict | 通过 |

## ruff S 存量处置

- 2096 条起步：2049 S101 在 tests；按手顺 `tests/**` 放行
  S101/S104/S105/S106/S107/S108/S301/S603/S607（测试只处理本地夹具）。
- 生产代码 8 处 `assert` 改显式 raise（app、library×3、routes_graph_wiki、
  settings、sync/service×2），`-O` 下行为一致。
- 误报逐条 `# noqa` + 原因：8 S608（占位符/常量列名拼接）、6 S603 / 1 S607
  （固定命令数组、无 shell）、2 S310（固定 https URL/本机冒烟端点）、
  1 S104（监听警告比较）、1 S105（`_TOKEN_TRAILING` 名称误判）。
- `RUF100` 保证没有未使用的 noqa。

## 保留判断

- CodeQL Rust 无支持，由 clippy + cargo-audit 兜底。
- 未引入 Semgrep/Snyk/SonarQube。
- CodeQL 实际 SARIF 上报需 GitHub Actions 解锁后首跑确认（当前账号账单锁定）。
