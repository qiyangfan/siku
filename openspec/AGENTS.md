# openspec — 规格驱动开发（spec-driven）

- `project.md`：**项目宪法**（不可协商红线 6 条 + 工程口径），先于任何编码阅读。
- `config.yaml`：硬约束清单（注入每次 AI 请求的 context 与 rules）。
- `specs/`：主规格（当前 0 能力，随首个 change 归档生成），每能力一个 `spec.md`
  （Purpose + Requirements + Scenario）。归档变更时 delta 在此合并，是行为的唯一权威口径。
- `changes/`：活跃变更（proposal/design/specs delta/tasks/review.md 全件）。
  流程：propose（全件 + strict 校验）→ apply（逐任务实现 + 勾选）→ 独立评审（review.md）
  → archive（移入 `changes/archive/YYYY-MM-DD-*/`）。
- `tasks.md` 全部勾选只表示实现任务完成；归档前仍须完成测试、门禁和 `review.md` 证据。
- 校验：`openspec validate --changes --strict` / `--specs --strict`。

## 硬规则

- MODIFIED Requirements 必须保留原需求全部 Scenario 名（整块替换，丢场景名 archive 报错）
- proposal 必须含 Non-goals 并引用受影响 ADR；任务粒度 ≤ 2 小时
- 无 spec 级行为变化的纯重构/工具变更需在 `.openspec.yaml` 声明 `skip_specs: true`
- 技能入口：`.agents/skills/openspec-*`（propose/apply/archive/sync/update/explore）
