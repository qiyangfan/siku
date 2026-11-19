# 任务清单

每批独立验证；验证命令均为等价 CI 命令（本机 gitleaks 8.30.1 与 CI 钉版本一致）。

## 1. 扫描策略实现

- [x] 1.1 新增 `.gitleaks.toml`（`extend` 默认规则；路径豁免 `tests?/fixtures`、
  `docs` 图文、`ui/src-tauri/binaries/`；值豁免 `cjk-uni-bigram` 与
  `SIKU_E2E_PLACEHOLDER_KEY`，逐条注释原因）——验证：加入前基线 5 处
  `generic-api-key` 误报，加入后 `gitleaks detect --source . --redact --exit-code 1`
  退出 0（89 commits, no leaks found）。
- [x] 1.2 `.pre-commit-config.yaml` 首位加 gitleaks v8.30.1 hook——验证：
  `uv run pre-commit validate-config` 通过。`uv run pre-commit run gitleaks --all-files`
  因拉取 hook 环境网络无进展（7 分钟空转，已终止）未取得实跑证据，交 CI 兜底。

## 2. CI 落点

- [x] 2.1 新增 `.github/workflows/security.yml`：`secrets` job（checkout@v7
  `fetch-depth: 0`、gitleaks 8.30.1、timeout 10、`contents: read`、无
  `continue-on-error`）——验证：`actionlint` 退出 0。
- [x] 2.2 按 handoff §5.0 对齐存量 Actions 版本：`setup-uv` `v10.3.0` → `v10.3.3`
  （`ci.yml` 3 处、`release.yml` 1 处）——验证：`actionlint` 退出 0。

## 3. 负向验收

- [x] 3.1 干净树全绿：等价 CI 命令退出 0（输出见 review.md）。
- [x] 3.2 人为植入一次违规：临时克隆提交 `leak-probe.txt` 后同命令退出 1，
  finding 指向该文件（`aws-access-token`）；探针改用随机键，原因见 design.md D4。
- [x] 3.3 移除探针后恢复为 0。
- [x] 3.4 新文件自身不触发门禁：把本批全部文件复制进临时克隆并提交后，
  同命令退出 0（模拟合并后的历史）。
- [x] 3.5 错误面不越界：本件零 Python/UI 源码改动（改动清单见 HANDOFF）。

## 4. 分支保护 required

- [ ] 4.1 将 `security / secrets` 设为 `main` 的 required check——**阻塞**：账号级
  Actions 锁定自 2026-11-09 未解除，job 不会上报；此时设 required 会把所有 PR 永久卡住。
  待 CI 可跑、首跑绿后在同轮授权下执行（gh 命令见 review.md「待授权动作」）。

## 5. 收尾

- [x] 5.1 `openspec validate 2026-11-19-add-secret-scanning --strict` 通过。
- [x] 5.2 `docs/HANDOFF.md` 整体重写（≤60 行）：改动清单、验证证据、遗留项。
- [ ] 5.3 推送与提交按用户逐次授权执行；PR 合并后归档本 change（`skip_specs`）。

## Workflow follow-up

- Archive this change after merge and backfill the gate matrix into `docs/HANDOFF.md`.
