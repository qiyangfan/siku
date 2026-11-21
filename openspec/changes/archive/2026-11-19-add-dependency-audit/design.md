# 设计：三语言依赖漏洞扫描的选型与落点

## Context

见 proposal.md「Why」。原则来自跨仓手顺 §P0-2：扫锁定文件，不扫"当前环境漂移"；
每个语言用原生工具。

## Decisions

### D1 Python 用 pip-audit，跑在锁定的项目环境

`uv sync --locked` 后 `uv run pip-audit`。pip-audit 审计的是虚拟环境，但环境由
`uv.lock` 唯一决定，等价于扫锁定文件；不在 `uvx` 隔离环境里跑（那会审计到
pip-audit 自己的依赖，口径错误）。

### D2 Rust 用 cargo-audit 扫 Cargo.lock

`cargo audit --file ui/src-tauri/Cargo.lock`。CARGO 环境不安装项目依赖也能审计，
故 job 不需要 Tauri 系统库。版本钉 0.23.0，与本地实测一致。
仅漏洞阻断；unmaintained/unsound 为 RustSec 无修复版的警告，保持默认放行。

### D3 JS 用 osv-scanner 为主，npm audit 为辅

osv-scanner 直接扫 `package-lock.json`，不依赖 registry 凭据；npm audit 会受私有源
401 影响，仅作补充。两者阈值：npm 只阻断 high 及以上，osv-scanner 默认全量阻断。

### D4 落点：security.yml 的三个独立 job

security workflow 已有"不允许被路径门控跳过"的约定，直接追加 `python-deps` /
`rust-deps` / `js-deps` 三个 job，与 secret job 同级；任一失败即 workflow 失败。
不放进 ci.yml，避免被 changes 路径过滤误跳过。

### D5 存量修复顺序

先升级到修复版本再开闸：pypdf 系列 CVE 需 6.21.2~6.21.4；pillow 需 13.0.0，而
docling 2.140.0 的 `pillow<13` 使其不可达——升级 docling 全家桶到 2.150.1
（`pillow<14`）后 pillow 13.0.0 可解析。Cargo 侧 `cargo update` 即消除两条漏洞。

## Risks / Trade-offs

- [pypdf 5→7 主版本变更] → 现有 PDF 抽取测试与全量回归验证；失败则回退并改用
  6.21.4（仍无 CVE）。
- [docling 升级引入新依赖] → docling 属可选 extra，核心安装不受影响；`uv sync`
  与 sidecar 构建路径需回归。
- [npm audit 网络抖动] → 仅作补充门禁；osv-scanner 为主判据。

## Migration Plan

无数据/接口迁移。回滚 = 还原本 change 涉及的配置与锁文件；依赖升级可独立保留。

## Open Questions

无。
