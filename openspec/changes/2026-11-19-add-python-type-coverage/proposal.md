# 提案：mypy 与覆盖率阈值进 CI（P1 Python）

## Why

跨仓质量门禁批次 5 / P1。`mypy` 早已配置却从未在 CI 执行——配置漂移无人发现；
`pytest-cov` 在 dev 依赖里但没有任何阈值，覆盖率下降不会阻断。实测 `uv run mypy`
直接因 `tests/conftest.py` 与 `tests/e2e/conftest.py` 模块重名退出 2，从未真正检查过代码。

## What Changes

- 修掉 mypy 在 `src/` 的 5 处基线错误：providers 两个生成器的类型收窄、settings 协议
  异常分型、mcp 上下文管理器返回类型、app OpenAPI 安装函数的误 return。
- `pyproject.toml`：`[tool.mypy] files` 收敛为 `["src"]`（tests 的模块重名需独立重构
  导入方式）；新增 `[tool.coverage.run]`（source=siku、branch=true）与
  `[tool.coverage.report]`（show_missing、fail_under=89）。
- `ci.yml` 测试 job 3.12 桶追加 `uv run mypy`；测试步骤改为
  `uv run pytest --cov=siku --cov-report=term-missing`。

## 关键数字

- mypy：`Success: no issues found in 85 source files`。
- 覆盖率：行+分支合计 **89.97%**（6836 语句 / 576 未覆盖 / 1452 分支 / 181 部分），
  `fail_under` 取向下取整 **89**。语句覆盖 92%、分支覆盖 82%。

## 受影响决策

只引用、不修改：ADR-0008（门禁加入既有测试 job，不新增矩阵桶）。`skip_specs: true`。

## Impact

文件面：`pyproject.toml`、`.github/workflows/ci.yml`、5 处 src 类型修复。
零运行时行为变化。

## Non-goals（不做清单）

- 不引入 pyright（kongming 有，但本仓本轮只按手顺补 mypy）。
- 不把 tests/ 纳入 mypy（模块重名需改导入结构，独立排期）。
- 不为提升覆盖率补测试；阈值只锁基线。
