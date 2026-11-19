# 任务清单

验证一律用 `env -u DASHSCOPE_API_KEY -u NO_PROXY -u no_proxy uv run ...`。

## 1. CodeQL

- [x] 1.1 新增 `.github/workflows/codeql.yml`（python + javascript-typescript，
  push main / PR / 周定时）——验证：actionlint 通过。
- [x] 1.2 负向验收：PR 事件路径与权限可被 CodeQL 接受（workflow 语法校验通过；
  实际上报需 GitHub Actions 解锁后首跑确认）。

## 2. ruff S

- [x] 2.1 `pyproject.toml` select 增加 `S`，`tests/**` 放行 9 条测试惯用规则。
- [x] 2.2 生产代码 8 处 assert 改显式 raise；全量 pytest 887 passed。
- [x] 2.3 误报逐条 `# noqa` 注明原因（8 S608 / 6 S603 / 1 S607 / 2 S310 / 1 S104 / 1 S105）
  ——验证：`ruff check .` 0，`RUF100` 无未使用 noqa。
- [x] 2.4 负向验收：临时植入 `subprocess.run(user_input, shell=True)`，
  `ruff check` 退出 1（S602）；移除后回 0。

## 3. 收口

- [x] 3.1 `openspec validate 2026-11-19-add-codeql --strict` 通过。
- [x] 3.2 文档回写 proposal/design/tasks 与 HANDOFF。
