# 评审记录：依赖漏洞门禁

## 验证证据（本机实测）

| 项 | 结果 |
|---|---|
| `uv run pip-audit` | **0 known vulnerabilities**（修复前 45 条 / 3 包） |
| `cargo audit --file ui/src-tauri/Cargo.lock` | **0 vulnerabilities**，6 allowed warnings（unmaintained/unsound） |
| `npm audit --omit=dev --audit-level=high` | 0 vulnerabilities（修复前 10，含 1 high） |
| `osv-scanner scan source -L ui/package-lock.json` | 0 issues（298 packages） |
| actionlint（security.yml） | 通过 |
| openspec strict | 通过 |

## 存量修复

- Python：pypdf 6.21.1→7.1.1、setuptools 84.0.0→84.2.1、certifi→2026.10.23、
  opentelemetry-api→1.45.2；docling 全家桶 2.140.0→2.150.1 解除 `pillow<13`，
  pillow→13.0.0（42 条 CVE）。
- Rust：`cargo update` 升级 rustls-webpki / webpki-roots（2 条漏洞消失），
  另修复 yanked 的 async-executor。
- JS：`npm audit fix --package-lock-only` 消除 minimatch/zod dev 漏洞。

## 负向验收

- 临时 requirements 固定 pypdf==6.21.1：pip-audit 退出 1（CVE-2026-119204 等）。
- HEAD 旧 Cargo.lock：cargo audit 退出 1（2 vulnerabilities）；升级后退出 0。

## 保留判断

- 未使用任何 `--ignore-vuln`；cargo 的 unmaintained 警告保持默认放行（无修复版本，
  升级为 deny 会永久卡死）。
- js 门禁只扫前端锁文件：全仓扫描会把 RustSec 的 unmaintained 告警当漏洞误伤，
  Python/Rust 已各有原生工具。

## 遗留

- 依赖自动更新已扩到 uv/npm/cargo 三个生态（monthly）。
- 外部 CI 未绿（账号账单锁定），change 保持 active。
