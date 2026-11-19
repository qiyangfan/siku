# 提案：依赖漏洞门禁——pip-audit / cargo-audit / osv-scanner 三语言进 CI

## Why

跨仓质量门禁批次 2 / P0-2。本仓此前只依赖 Dependabot（且仅覆盖 GitHub Actions），
没有阻断式漏洞扫描：实测 `uv run pip-audit` 报 **45 条漏洞（3 个包）**——pypdf 6.21.1
的 11 条、setuptools 84.0.0 的 1 条、pillow 12.3.0 的 42 条（被 docling 的
`pillow<13` 约束锁死）；`cargo audit` 报 **2 条漏洞**（rustls-webpki、webpki-roots）。
依赖一旦带病合入，发布产物即带病。

## What Changes

- `pyproject.toml` dev 组增加 `pip-audit>=2.9`；升级 `pypdf`→7.1.1、`setuptools`→84.2.1、
  `certifi`→2026.10.23、`opentelemetry-api`→1.45.2，并把 docling 可选后端升到 2.150.1
  （其 `pillow<14` 约束允许 pillow 13.0.0），`uv.lock` 随之更新。
- `cargo update` 升级 `rustls-webpki`/`webpki-roots`，`ui/src-tauri/Cargo.lock` 更新。
- `.github/workflows/security.yml` 增加三个阻断 job：
  `python-deps`（`uv sync --locked` + `uv run pip-audit`）、
  `rust-deps`（`cargo install cargo-audit@0.23.0` + `cargo audit`）、
  `js-deps`（`osv-scanner` 扫锁定文件 + `npm audit --omit=dev --audit-level=high` 补充）。
- `.github/dependabot.yml` 增加 `uv` / `npm` / `cargo` 三个生态，月度更新。

## 受影响决策

只引用、不修改：ADR-0008（CI 版本矩阵——门禁加入既有 security workflow，不引入新版本矩阵）。
本件不改变产品行为，`.openspec.yaml` 声明 `skip_specs: true`。

## Impact

文件面：`pyproject.toml`、`uv.lock`、`ui/src-tauri/Cargo.lock`、
`.github/workflows/security.yml`、`.github/dependabot.yml`。
运行时行为不变；三语言漏洞存量清零。

## Non-goals（不做清单）

- 不做 CodeQL（P0-3）、SBOM + 许可证（P0-4），各自独立 change。
- 不用 `--ignore-vuln` / `--ignore` 跳过任何漏洞；不降级为 `continue-on-error`。
- 不把 `cargo audit` 的 unmaintained/unsound 警告升级为阻断（RustSec 无修复版本，
  升级为 `--deny warnings` 会永久卡死；漏洞本身仍阻断）。
- 不做 Actions 钉 SHA（P2）；不改动现有 secret job。
