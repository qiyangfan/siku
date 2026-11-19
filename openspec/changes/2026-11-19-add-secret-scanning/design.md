# 设计：gitleaks 门禁落位与误报收敛

## Context

见 proposal.md「Why」。现状约束：

- 本仓无 `.gitleaks.toml`、无 `security.yml`；`ci.yml` 有路径门控（`changes` job）。
- 本机 gitleaks 8.30.1（与 handoff 钉版本一致），基线扫描 89 个提交：
  5 处 `generic-api-key` 误报——`cjk-uni-bigram-v1`（`benchmarks/*.json`、
  `src/siku/retrieve/tokenizer.py`）、`cjk-uni-bigram-v0-ancient`（测试）、
  `SIKU_E2E_PLACEHOLDER_KEY`（`tests/e2e/conftest.py`）。无真实密钥。
- 账号级 Actions 锁定自 2026-11-09 未解除，`security` job 首跑与 required 设置被阻塞。

## Goals / Non-Goals

- 目标：PR/推送即阻断密钥泄露，且门禁自身可被负向验证证伪。
- 不做：见 proposal.md「Non-goals」。设计层额外排除——不按规则名整体禁用、不整目录豁免
  非夹具路径、不扫描工作树之外的产物。

## Decisions

### D1 独立 `security.yml`，不并入 `ci.yml`

`ci.yml` 的作业按路径裁剪，安全作业一旦挂在里面就会被路径过滤跳过；handoff §2 统一落点
也是独立 workflow。并发组 `security-<ref>` 取消旧运行，与 ci 同哲学。

### D2 `detect` + `fetch-depth: 0`（全历史），不只用 diff

PR 门禁要看"合入后历史里有什么"，只看增量会让历史遗留泄露永久放行。代价是每次扫全史
（本仓 ~4.7 MB / 89 提交，本机 1–3 s），10 分钟 timeout 余量充足。

### D3 误报处置：路径级 + 窄值级，不用规则级豁免

- 路径：`tests?/fixtures`、`docs/.*\.(md|png|jpg)$`（handoff 默认）+ siku 专属
  `ui/src-tauri/binaries/`（打包产物，二进制误报）。逐条注释原因。
- 值：`stopwords = ["cjk-uni-bigram", "SIKU_E2E_PLACEHOLDER_KEY"]`。分词版本号每次升级
  都会出现新值，正则按整串匹配会反复失效；`cjk-uni-bigram` 前缀稳定且可审计。
- 备选：按规则 `generic-api-key` 加 allowlist——被拒，等同按规则全局放行（handoff §6）。

### D4 负向验证换探针值

handoff 的探针 `AKIAIOSFODNN7EXAMPLE` 被 gitleaks 8.30.1 内置"示例键"豁免过滤，实测
`detect` 退出 0——照抄会得到一条永远绿的假门禁。改用同形态随机键（本文件不落原文，
见 review.md 证据，形态 `AKIA` + 16 位随机大写字母数字），`aws-access-token` 命中、
退出 1。这是修正验证方法，不是放宽门禁；反向约束——探针原文不得写进任何入库文件，
否则门禁把自己的验证探针判红。

### D5 版本与复用

gitleaks 8.30.1（CI 下载 + pre-commit rev 同源）；Actions 按 handoff §5.0：
`actions/checkout@v7`、`astral-sh/setup-uv@v10.3.3`（存量 v10.3.0 顺带对齐，仍钉精确版本）。
pre-commit hook 与 CI 共用 `.gitleaks.toml`，避免两套口径。

### D6 分支保护 required 延后

账号级 Actions 锁定期间 job 不上报，required check 永远 pending 会卡死所有合并。策略：
先留 workflow 与本地证据，锁定解除、首跑绿后在同轮授权下设置 required（gh 命令见 review.md）。

## Risks / Trade-offs

- [历史误报永久进扫描范围] → 用 D3 窄豁免；新误报必须先改假值，再考虑路径豁免。
- [本地 gitleaks 版本与 CI 漂移] → CI 钉 8.30.1、pre-commit rev 同版本；升级时三处同改。
- [Required check 缺失导致门禁形同虚设] → HANDOFF 记为未闭环项，不冒充"已设 required"。
- [pre-commit 可被 `--no-verify` 绕过] → 属既定纪律（AGENTS.md 禁用 `--no-verify`），
  真正的执法面是 CI required check。

## Migration Plan

无数据/接口迁移。回滚 = 删除 `security.yml` 的 `secrets` job 与 pre-commit hook；
`.gitleaks.toml` 可保留（无副作用）。

## Open Questions

无。
