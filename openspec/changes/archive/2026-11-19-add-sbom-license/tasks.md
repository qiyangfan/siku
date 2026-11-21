# 任务清单

## 1. 策略与扫描面

- [x] 1.1 新增 `.grant.yaml`（allowlist + 7 条 ignore-packages，各带原因/复核日期）。
- [x] 1.2 新增 `.syft.yaml`（排除语料/构建产物，保留依赖安装目录）。
- [x] 1.3 本机 syft 1.57.2 生成 CycloneDX：1278 组件，`.syft.yaml` 排除生效。

## 2. 门禁接线

- [x] 2.1 security.yml 增加 `sbom-license`：uv sync + npm ci → sbom-action → grant check
  ——验证：actionlint 通过。

## 3. 验收

- [x] 3.1 干净树 `grant check` 退出 0（763 allowed / 7 ignored / 602 unlicensed /
  0 denied）。
- [x] 3.2 负向验收：构造含 GPL-3.0-only 组件的 SBOM，`grant check` 退出 1
  （1 denied，High）；移除后回 0。
- [x] 3.3 SBOM artifact 由 sbom-action 上传（默认留存 30 天）。
- [x] 3.4 `openspec validate 2026-11-19-add-sbom-license --strict` 通过。
