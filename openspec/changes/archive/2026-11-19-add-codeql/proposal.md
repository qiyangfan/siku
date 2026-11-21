# 提案：SAST——CodeQL 双语言扫描 + ruff 安全规则族进 lint

## Why

跨仓质量门禁批次 3 / P0-3。本仓此前没有静态应用安全测试：CodeQL 未接入，
ruff 的 bandit 等价规则集 `S` 未启用。SAST 与依赖漏洞扫描互补——后者看已知 CVE，
前者看代码里的危险模式（注入、命令执行、路径穿越等）。

## What Changes

- 新增 `.github/workflows/codeql.yml`：`python` 与 `javascript-typescript` 两语言矩阵，
  push(main)/PR/每周一 03:23 定时；`security-events: write` 上传结果。
  Rust 无 CodeQL 支持，由 clippy 与 cargo-audit 兜底。
- ruff `select` 增加 `S`（flake8-bandit）。处置实测 2096 条命中：
  - `tests/**` 放行 `S101,S104,S105,S106,S107,S108,S301,S603,S607`——测试只处理
    本地夹具（断言惯用法、临时目录、pickle 夹具、子进程启动），不接收不受信输入。
  - 生产代码 8 处 `assert` 改为显式 `raise`（应用工厂空值、runner 未配置、
    异常分型不匹配、暂存/报告缺失），不再受 `-O` 影响。
  - 经核实的误报逐条 `# noqa` 注明原因：8 处 S608（SQL 只拼接 `?` 占位符与常量列名，
    值全部参数化）、S603/S607（固定命令数组，不启用 shell）、S310（固定 https URL /
    本机冒烟端点）、S104（监听全网卡的警告比较）、S105（`_TOKEN_TRAILING` 变量名误判）。
- 前端 `npm audit` 补充门禁已随批次 2 落地；本件不重复。

## 受影响决策

只引用、不修改：ADR-0008（CI 版本矩阵——新 workflow 单一语言矩阵，不引入 Python
版本矩阵）。本件不改变产品行为，`skip_specs: true`。

## Impact

文件面：新增 `.github/workflows/codeql.yml`；`pyproject.toml`（ruff select +
per-file-ignores）；`src/siku/api/{app,library,routes_graph_wiki,settings}.py`、
`src/siku/sync/service.py`（assert→raise）；若干 `# noqa` 行。
运行时行为不变（仅 `-O` 下不变量检查从"消失"变为"显式报错"）。

## Non-goals（不做清单）

- 不引入 SonarQube/Snyk/Semgrep 等第三方 SAST。
- 不把 ruff `S` 的误报降级为 warn 或全局 disable；`# noqa` 必须带原因。
- 不做 SBOM/许可证（P0-4，独立 change）。
