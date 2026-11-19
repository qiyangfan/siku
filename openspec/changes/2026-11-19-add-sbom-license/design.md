# 设计：SBOM 生成与许可证 allowlist 的可用性边界

## Context

syft 从已安装包信息读取许可证；仅扫锁文件时 Cargo/uv 组件无 license 字段。
grant 是 allowlist（默认 deny-all），无法对未知许可证做判断。

## Decisions

### D1 先还原依赖再生成 SBOM

job 里先 `uv sync --locked` 与 `npm ci`，让 dist-info / node_modules 携带许可证元数据；
`.syft.yaml` 只排除语料、构建产物与 VCS，保留 `.venv`、`ui/node_modules`。

### D2 未知许可证跳过，已知许可证严格阻断

`require-license: false`、`require-known-license: false`。原因：Cargo.lock 与
uv.lock 不携带许可证，602 个组件无 license 字段；若要求 known，门禁永久红。
已知许可证仍按 allowlist 判定，强 copyleft 一律阻断（负向探针已证）。

### D3 非 SPDX 自由文本按名称加入 allowlist

syft 对部分 Python 包读到的是自由文本（`Apache 2`、`BSD 2-Clause License`、
`Expat license` 等）。逐条确认含义后将原文加入 allowlist，而不是按包名忽略；
`Dual License`（python-dateutil）与 reportlab 长文本含义不明确，才按包名
`ignore-packages` 并注明实际许可证。

### D4 构建/开发期 copyleft 的例外

pylint/astroid（开发期）、pyinstaller 系（打包期）、autocommand（开发期传递）
不进入发布产物，列入 `ignore-packages` 并写复核日期 2027-06-30。

## Risks / Trade-offs

- [Rust 许可证盲区] → 已知限制，SBOM artifact 留存供审计；后续可用 cargo-deny 补齐。
- [npm ci 增加 job 时长] → timeout 20 分钟，实测本机安装约 1 分钟。

## Migration Plan

无。回滚 = 删除 job 与两份配置。

## Open Questions

无。
