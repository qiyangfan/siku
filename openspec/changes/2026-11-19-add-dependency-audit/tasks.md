# 任务清单

验证一律用 `env -u DASHSCOPE_API_KEY -u NO_PROXY -u no_proxy uv run ...`。

## 1. 存量清零

- [x] 1.1 `pyproject.toml` dev 组加 `pip-audit>=2.9`，`uv lock`；升级 pypdf→7.1.1、
  setuptools→84.2.1、certifi→2026.10.23、opentelemetry-api→1.45.2。
- [x] 1.2 docling 全家桶升到 2.150.1 解除 `pillow<13` 约束，pillow→13.0.0。
- [x] 1.3 `cargo update` 升级 rustls-webpki / webpki-roots，消除 2 条漏洞。
- [x] 1.4 验证：`uv run pip-audit` 0、`cargo audit` 0 漏洞（仅警告）、
  `npm audit --omit=dev --audit-level=high` 0。

## 2. 门禁接线

- [x] 2.1 security.yml 增加 `python-deps` / `rust-deps` / `js-deps` 三个阻断 job
  ——验证：actionlint 通过。
- [x] 2.2 dependabot 增加 uv / npm / cargo 三个生态，月度。
- [x] 2.3 `openspec validate 2026-11-19-add-dependency-audit --strict` 通过。

## 3. 负向验收

- [x] 3.1 pip-audit 对含 pypdf 6.21.1 的临时 requirements 退出 1，对当前锁定环境退出 0。
- [x] 3.2 cargo audit 对 HEAD 旧 Cargo.lock（升级前）退出 1，对当前 lock 退出 0。
- [x] 3.3 osv-scanner 对 ui 锁定文件退出 0（本机临时二进制实测；CI 用同版本）。

## 4. 回归

- [x] 4.1 pypdf 主版本升级后 PDF 相关测试全绿。
- [x] 4.2 全量 pytest 与 ruff/pylint/lint-imports 全绿。
