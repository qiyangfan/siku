# 设计：治理自检的落点与工具边界

## Context

OpenSpec 与 actionlint 都是"元层"校验：它们不检查产品代码，而是检查治理文件本身。
若与业务 job 混放，容易被路径门控跳过或与语言矩阵耦合。

## Decisions

### D1 独立 governance job

`ci.yml` 新增 job，无路径门控、无矩阵；Node 24 + `npx @fission-ai/openspec@1.17.0`
与 actionlint 1.7.12。两者都是几秒级，合并为一个 job 控制流水线数量。

### D2 版本钉死

openspec 与 actionlint 均钉精确版本，避免"治理规则随上游漂移"导致历史 change
突然变红。

### D3 不引入的文本类 linter

commitlint：为一条规则引入根 Node 工具链不成比例，提交规范由 AGENTS.md 与评审执行。
markdownlint/taplo/yamllint：中文散文格式规则收益低；YAML/TOML 结构已由 pre-commit
check-yaml/check-toml 与 actionlint 覆盖。

## Risks / Trade-offs

- [npx 需要网络] → 与 setup-node 一致，失败即阻断，可接受。
- [actionlint 下载源] → GitHub Releases 固定版本 URL，与其它二进制下载同源。

## Migration Plan

无。回滚 = 删除 governance job。

## Open Questions

无。
