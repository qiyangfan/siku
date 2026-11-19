# 评审记录：SBOM + 许可证

## 验证证据（本机实测，syft 1.57.2 / grant 0.8.0）

| 项 | 结果 |
|---|---|
| syft 生成 CycloneDX | 1278 组件（`.syft.yaml` 排除生效，data/ 未入 SBOM） |
| `grant check` 干净树 | 退出 0：763 allowed / 7 ignored / **602 unlicensed** / 0 denied |
| GPL 探针 | 1 组件 GPL-3.0-only → 退出 1（1 denied, High）；移除后 0 |
| actionlint | 通过 |
| openspec strict | 通过 |

## 关键取舍

- `require-license: false` / `require-known-license: false`：Cargo.lock 与 uv.lock
  不携带 license 字段（602 个未知），强制 known 会让门禁永久红。已知许可证仍严格
  按 allowlist 阻断。
- 非 SPDX 自由文本（`Apache 2`、`BSD 2-Clause License`、`Expat license` 等）
  逐条确认后按原文加入 allowlist，不按包名放行。
- `ignore-packages` 7 项均为构建/开发期 copyleft（pylint/astroid/pyinstaller 系/
  autocommand）或语义不明确（python-dateutil Dual License、reportlab 自由文本），
  复核日期 2027-06-30。

## 遗留

- Rust 许可证元数据盲区：后续可引入 cargo-deny 补强，不阻塞本 change。
- SBOM 作为 artifact 由 sbom-action 上传，默认留存 30 天。
