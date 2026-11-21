# 提案：SBOM 生成 + 许可证 allowlist 门禁

## Why

跨仓质量门禁批次 4 / P0-4。仓库此前没有 SBOM，也没有许可证策略：引入 GPL/AGPL
依赖不会被任何门禁发现。公开发布后，许可证污染是法律风险而非工程风险，必须前置拦截。

## What Changes

- `.github/workflows/security.yml` 增加 `sbom-license` job：先 `uv sync --locked` 与
  `npm ci` 还原许可证元数据，再用 `anchore/sbom-action@v0` 生成 CycloneDX SBOM
  （artifact 留存），最后 `grant check` 执行 allowlist。
- 新增 `.grant.yaml`：allowlist 为宽松 + 弱 copyleft 许可；`ignore-packages` 仅
  7 个已逐条裁决的构建/开发期包（pylint、pyinstaller 系、autocommand、
  python-dateutil、reportlab），各带原因与 2027-06-30 复核日期。
- 新增 `.syft.yaml`：排除语料/本地数据/构建产物，保留 `.venv` 与 `ui/node_modules`
  （许可证元数据来源）。
- 本机基线：`grant check` 763 allowed / 7 ignored / 602 unlicensed / 0 denied。

## 已知限制

`Cargo.lock` 与 `uv.lock` 不携带许可证元数据，SBOM 中相应组件无 license 字段
（602 个），因此 `require-license` / `require-known-license` 置为 false：未知项跳过，
**已知许可证照常按 allowlist 阻断**。Rust 侧许可证由 `cargo-deny` 类工具补齐属后续
独立项。

## 受影响决策

只引用、不修改：ADR-0002（公开节奏——许可证问题必须在发布前发现）。`skip_specs: true`。

## Impact

文件面：`.github/workflows/security.yml`、`.grant.yaml`、`.syft.yaml`。
零运行时行为变化；每次 push/PR 产出 SBOM artifact。

## Non-goals（不做清单）

- 不引入 FOSSA/Snyk 等 SaaS 许可证服务。
- 不把 unlicensed 组件强行判失败（元数据缺口，非许可问题）。
- 不做容器扫描（本仓无 Dockerfile）。
