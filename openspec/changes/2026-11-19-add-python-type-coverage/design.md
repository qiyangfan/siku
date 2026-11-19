# 设计：mypy 范围与覆盖率阈值的取数口径

## Context

mypy 在 tests/ 因同名 `conftest.py` / `fakes.py` 模块重名无法启动；覆盖率此前
只有语句覆盖且无阈值。

## Decisions

### D1 mypy 先收 src，tests 暂不纳入

`files = ["src"]`。tests 的重名问题需要把测试改为包导入（加 `__init__.py`）或
拆分 conftest，属独立导入结构改造；本轮先让 CI 真正检查 85 个生产源文件。
不改 `ignore_missing_imports`、不降 strict 相关开关。

### D2 覆盖率取行+分支合计，阈值向下取整

`branch = true`，`source = ["siku"]`。实测 89.97%，`fail_under = 89`。
若只报语句覆盖会显示 92%，与阈值口径不一致，故文档中同时记录两个数字。

### D3 门禁放 3.12 桶

mypy 与覆盖率只在 3.12 执行一次（矩阵另一桶 3.14 仍跑 ruff 与 pytest），
避免重复耗时，与 pylint/import-linter 的落点一致。

## Risks / Trade-offs

- [tests 不类型检查] → 已知取舍；生产代码全覆盖，后续独立变更收紧 tests。
- [覆盖率阈值锁在 89%] → 只降不升；新增未覆盖代码会稀释比例并可能触发阈值。

## Migration Plan

无。回滚 = 还原 mypy files 与 coverage 配置、移除 CI 两步。

## Open Questions

无。
