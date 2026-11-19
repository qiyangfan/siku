# 设计：CodeQL 矩阵与 ruff S 的存量处置

## Context

见 proposal.md。CodeQL 提供跨文件数据流分析；ruff S 提供单文件模式匹配。
两者重叠但不等价，均按跨仓手顺落地。

## Decisions

### D1 CodeQL 语言矩阵

`python` 与 `javascript-typescript`。Rust 没有 CodeQL 支持，桌面壳由
`cargo fmt/clippy/test`（ci.yml）与 `cargo audit`（security.yml）覆盖。
`autobuild` 对 Python 无需构建，对 TS 自动执行包安装；CI 不额外指定构建命令。

### D2 触发与权限

push(main) + pull_request + 每周一 03:23 定时。`security-events: write` 仅授予
analyze 所需；`contents: read` 保持最小权限。定时扫描用于捕捉查询包更新后的新发现。

### D3 ruff S 的测试级放行

`tests/**` 放行 `S101,S104,S105,S106,S107,S108,S301,S603,S607`，理由：
- S101：pytest 的断言即测试本体；
- S104/S105/S106/S107：测试里出现的是地址字面量与占位凭证；
- S108/S301：临时目录与 pickle 只用于本地夹具；
- S603/S607：e2e 测试需要启动 `siku serve` 子进程。
生产代码（`src/`、`scripts/`、`benchmarks/`）不放行任何 S 规则。

### D4 生产代码：能修则修，误报才抑制

8 处 `assert` 全部改为显式 `raise`：应用工厂返回值由类型保证非空后不再需要断言；
runner 未配置、异常分型不符、暂存/报告缺失都是不可达的编程错误，显式抛出后
`-O` 下行为一致。SQL/子进程/URL 类命中经逐点核查为误报，`# noqa` 均带中文原因，
并由 `RUF100`（未使用 noqa 检测）反向保证没有多余的抑制。

## Risks / Trade-offs

- [CodeQL 首跑需 Actions 解锁] → workflow 与 actionlint 已验证；上报结果待账号账单
  解除后确认，期间保持 change active。
- [assert→raise 改变异常类型] → 全量 887 测试通过；正常路径不变。

## Migration Plan

无数据迁移。回滚 = 删除 codeql.yml、还原 ruff select 与 assert 行。

## Open Questions

无。
