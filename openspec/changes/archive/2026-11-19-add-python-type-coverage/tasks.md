# 任务清单

## 1. mypy

- [x] 1.1 定位并修复 5 处 src 基线错误（providers×2、settings、mcp、app）。
- [x] 1.2 `[tool.mypy] files = ["src"]`，tests 排除原因写入配置注释。
- [x] 1.3 验证：`uv run mypy` 退出 0（85 files）。
- [x] 1.4 负向验收：植入无注解函数，mypy 退出 1（no-untyped-def）；移除后回 0。

## 2. 覆盖率

- [x] 2.1 实测分支覆盖率基线：89.97%（行+分支），fail_under=89。
- [x] 2.2 `[tool.coverage.run]` / `[tool.coverage.report]` 落地，CI 测试步骤带 `--cov`。
- [x] 2.3 验证：门禁下全量 887 passed、退出 0。
- [x] 2.4 负向验收：`coverage report --fail-under=99` 退出 2。

## 3. 收口

- [x] 3.1 `openspec validate 2026-11-19-add-python-type-coverage --strict` 通过。
- [x] 3.2 actionlint 通过。
