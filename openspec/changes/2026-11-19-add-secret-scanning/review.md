# 评审记录：2026-11-19-add-secret-scanning

> apply 阶段实现证据（2026-11-19）；独立评审已于 2026-11-21 本地完成（见文末），
> 归档仍待 PR 合并。

## 实现证据

| 项 | 证据 |
|---|---|
| 扫描策略 | `.gitleaks.toml`（`extend` 默认规则 + 三条路径豁免 + 两条 stopword） |
| 基线收敛 | 加入前：`gitleaks detect --source . --redact --exit-code 1` → `leaks found: 5`（全部 `generic-api-key`：`cjk-uni-bigram-v*` ×4、`SIKU_E2E_PLACEHOLDER_KEY` ×1，均在 89 个提交内，无真实密钥）；加入后：`89 commits scanned ... no leaks found`，退出 0 |
| pre-commit | 首位 gitleaks `rev: v8.30.1`；`uv run pre-commit validate-config` 通过 |
| CI 落点 | `.github/workflows/security.yml`：`secrets` job，checkout@v7 `fetch-depth: 0`，gitleaks 8.30.1，timeout 10，`permissions: contents: read`，无 `continue-on-error`/`|| true` |
| Action 版本对齐（handoff §5.0） | `astral-sh/setup-uv` `v10.3.0`→`v10.3.3`：`ci.yml` ×3、`release.yml` ×1；其余存量版本与基准表一致 |
| 工作流静态检查 | `actionlint security.yml ci.yml release.yml` → 退出 0 |
| openspec | `openspec validate 2026-11-19-add-secret-scanning --strict` → `is valid`（skip_specs 生效） |

## 负向验收（等价 CI 命令）

命令：`gitleaks detect --source . --redact --verbose --exit-code 1`（本机 8.30.1 = CI 钉版本）。
探针在临时克隆 `/tmp/siku-leak-probe` 中提交，避免污染本仓历史与工作树。

1. **干净树**：`89 commits scanned ... no leaks found` → 退出 **0**。
2. **植入违规**：提交 `leak-probe.txt`（`aws_access_key_id = AKIA` + 16 位随机字符，
   原文不落入库文件）后：
   ```
   Finding:     aws_access_key_id = REDACTED
   RuleID:      aws-access-token
   File:        leak-probe.txt
   Line:        1
   WRN leaks found: 1
   ```
   退出 **1**。
3. **移除后恢复**：`git reset --hard HEAD~1` 后同命令 → 退出 **0**。

> handoff 原探针 `AKIAIOSFODNN7EXAMPLE` 实测退出 0——被 gitleaks 8.30.1 内置"示例键"
> 豁免过滤。属验证方法缺陷，已按 design.md D4 换同形态随机键，门禁未放宽。

## 待授权动作（本轮未执行）

1. **分支保护 required**——阻塞于账号级 Actions 锁定（2026-11-09 起，见 HANDOFF）：
   job 不上报时设 required 会卡死全部 PR。锁定解除、`security / secrets` 首跑绿后执行：
   ```bash
   gh api -X PUT repos/qiyangfan/siku/branches/main/protection \
     -H 'Accept: application/vnd.github+json' \
     -F 'required_status_checks[strict]=true' \
     -f 'required_status_checks[contexts][]=security / secrets' \
     -F 'enforce_admins=true' \
     -F 'restrictions='
   ```
   实际执行前按仓库当时的 ruleset 现状复核（当前 `rulesets` 为空、`main` 未受保护）。
2. **提交与推送**：按用户逐次授权；推送后观察 `security` 首跑与 required 生效。
3. **pre-commit 本机实跑**：`uv run pre-commit run gitleaks --all-files` 需联网拉取
   hook 环境，7 分钟无进展已终止（网络受限）；`validate-config` 已通过，语义面由 CI
   同为 gitleaks 8.30.1 + 同一 `.gitleaks.toml` 兜底。

## 遗留

- 分支保护 required 未设（原因见上），HANDOFF 已记。
- CI 首跑未执行（账号级锁定 + 未推送）。

## 归档前清单

- [x] 独立评审（2026-11-21，本地复核，结论见文末）
- [ ] `security / secrets` 首跑绿、设为 required——阻塞：账号级 Actions 锁定未解除
- [ ] 门禁矩阵回填 `docs/HANDOFF.md`——依赖上一条的首跑结果

## 独立评审（2026-11-21）

本地可验证部分逐项复核，未发现需要返工的缺陷：

- `.gitleaks.toml` 与本文描述一致：`extend.useDefault`、3 条路径豁免、2 条 stopword，
  无按规则名全局放行；
- `.github/workflows/security.yml` 的 `secrets` job：`fetch-depth: 0`、
  `persist-credentials: false`、版本 8.30.1、下载后 checksums 校验、无
  `continue-on-error`/`|| true`；
- pre-commit 首位 hook 为 `gitleaks v8.30.1`，与 CI 共用同一配置文件；
- 实测 `gitleaks detect --source src --no-git --config .gitleaks.toml` → no leaks
  （不显式给 `--config` 时子目录扫描会漏掉 stopword，出现 1 条
  `cjk-uni-bigram` 假命中——这正是配置文件按仓库根注入的预期行为）。

仍待外部条件：首跑绿、required、HANDOFF 回填（同上清单）。
