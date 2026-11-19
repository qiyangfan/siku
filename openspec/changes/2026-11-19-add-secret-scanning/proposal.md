# 提案：Secret scanning 门禁——gitleaks 全历史扫描进 CI 与 pre-commit

## Why

仓库即将公开，本仓至今没有任何密钥泄露防线：历史提交与 PR 里的凭证一旦合入就是永久
暴露（GitHub 公开仓库的提交会被爬虫索引，删除文件不等于删除历史）。这是跨仓质量门禁
`../QUALITY-GATES-HANDOFF.md` 的批次 1 / P0-1，也是六仓 P0 中成本最低、风险最高的一项：
本地基线扫描已证实现行历史可用窄豁免收敛（5 处 `generic-api-key` 误报全部为分词版本号
与 e2e 占位键，无真实密钥）。现在落地，后续批次（依赖漏洞、CodeQL、SBOM）才有基线可挂。

## What Changes

- 新增 `.gitleaks.toml`：`extend` 默认规则；路径级豁免仅 `tests/fixtures`、`docs` 图文、
  siku 专属 `ui/src-tauri/binaries/`（打包产物二进制误报）；值级豁免仅 `cjk-uni-bigram`
  分词版本号与 `SIKU_E2E_PLACEHOLDER_KEY` 占位值，逐条注释原因。
- 新增 `.github/workflows/security.yml`：独立 `secrets` job（`gitleaks detect` 全历史、
  `fetch-depth: 0`、gitleaks 8.30.1、timeout 10）——不并入 `ci.yml`，避免路径门控跳闸。
- `.pre-commit-config.yaml` 首位加 gitleaks v8.30.1 hook，与 CI 共用同一配置文件。
- 按手顺 §5.0 顺带对齐存量 Actions 版本：`setup-uv` `v10.3.0` → `v10.3.3`
  （`ci.yml` 3 处、`release.yml` 1 处，仍钉精确版本）。

## 受影响决策

只引用、不修改：ADR-0008（CI 版本矩阵——Actions 版本按 handoff §5.0 基准，不新开决策）、
ADR-0002（三阶段发布——公开节奏是"历史泄露 = 永久暴露"这一依据的来源）。本件不改变任何
产品行为，由 `.openspec.yaml` 声明 `skip_specs: true`（先例：`2026-11-09-add-ci-e2e-smoke`）。

## Impact

文件面：新增 `.gitleaks.toml`、`.github/workflows/security.yml`；修改
`.pre-commit-config.yaml`、`.github/workflows/ci.yml`、`.github/workflows/release.yml`。
零新增依赖、零运行时改动、零产品可观察变化。门禁面：干净树退出 0；刻意植入凭证时
`security / secrets` 必须失败。分支保护 required 待账号级 Actions 锁定解除后设置
（期间 workflow 不上报，设为 required 会把 PR 永久卡死），见 tasks.md 批次 D。

## Non-goals（不做清单）

- 不做依赖漏洞/CodeQL/SBOM+license（批次 2/3/4，各自单独 change）。
- 不重写 git 历史、不轮换凭证（基线扫描无真实密钥，无需触发）。
- 不引入 `|| true`、`continue-on-error`、`--no-git` 降级或规则级全局放行。
- 不改其他仓；不做 P2 的 Actions 钉 SHA（另行批次）。
- 不在本次执行 git commit / push：按用户逐次授权纪律，改动留在工作树。
- 不改任何 spec 级行为（门禁类改动，`skip_specs: true`）。

## 与项目路线的关系

质量门禁不占 `docs/ROADMAP.md` 的产品排序队列，排序由
`../QUALITY-GATES-HANDOFF.md` §5 批次决定（本件 = 批次 1，六仓各一 PR 的 siku 份）。
完成后门禁矩阵回填 `docs/HANDOFF.md` 与本 change 归档。
