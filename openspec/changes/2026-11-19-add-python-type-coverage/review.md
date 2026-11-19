# 评审记录：mypy + 覆盖率阈值

## 验证证据（本机实测）

| 项 | 结果 |
|---|---|
| `uv run mypy` | 退出 0：`Success: no issues found in 85 source files` |
| mypy 负向探针 | 无注解函数 → 退出 1（no-untyped-def）；移除后 0 |
| `pytest --cov=siku` | 887 passed，退出 0 |
| 覆盖率基线 | 89.97%（行+分支），fail_under=89 |
| `coverage report --fail-under=99` | 退出 2（Coverage failure） |
| actionlint | 通过 |

## 修复的 5 处基线错误

- `graph/providers.py`×2：生成器内 `Any | None` 收窄改为显式循环 + isinstance。
- `api/settings.py`：协议异常映射前显式校验类型。
- `mcp/server.py`：`@contextmanager` 函数补 `Iterator[None]` 返回注解。
- `api/app.py`：`-> None` 函数删除多余 `return application`。

## 保留判断

- `files = ["src"]`：tests 的 `conftest.py` / `fakes.py` 同名导致 mypy 无法启动；
  改为包导入需独立重构，本轮先覆盖全部生产代码。
- 覆盖率阈值取行+分支合计的向下取整 89（仅语句覆盖会显示 92%，口径不同）。
- 未引入 pyright。
