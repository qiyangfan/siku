# 任务清单

## 1. markdownlint

- [x] 1.1 新增 `.markdownlint-cli2.jsonc`：globs 人写文档、ignores HANDOFF、
  MD013 120 列（code_blocks/tables 豁免）、MD060 关闭（理由入注释）。
- [x] 1.2 首跑存量分类：511 处（默认 80 列）→ 120 列口径 76 处 MD013、
  365 处 MD060、30 处 MD041（openspec delta 形态）、其余结构类。
- [x] 1.3 修复超宽长段 12 处（README、architecture、ADR-0001/0011/0013）。
- [x] 1.4 补围栏语言 3 处（ADR-0004/0006、architecture）。
- [x] 1.5 ROADMAP 列表符号 6 处归 `+`、序号 3 处归 2/3/4。
- [x] 1.6 MASTER.md 行内登记 MD013 豁免（表内 token 路径不可折行）。
- [x] 1.7 验证：`npx --yes markdownlint-cli2@0.24.1` 22 文件 0 问题。

## 2. 链接与锚点

- [x] 2.1 新增 `scripts/check_md_links.py`：路径存在性、目录链接、百分号解码、
  括号目标、GitHub slug 锚点、同名去重、HTML id/name、`{#id}`。
- [x] 2.2 剔除围栏与行内代码，保持行号；外部链接零网络跳过。
- [x] 2.3 `tests/test_docs_links.py` 改为解析器单测（4 例），全仓扫描归脚本。
- [x] 2.4 负向验证：临时树注入坏路径/坏锚点/坏引用式定义 → exit 1 并逐条报行号。
- [x] 2.5 验证：`uv run python scripts/check_md_links.py` 257 文件 0 坏链。

## 3. 接入

- [x] 3.1 pre-commit 增加 `markdownlint`（npx 钉 0.24.1）与 `markdown-links`
  （uv run 脚本）两个 hook，实跑 Passed。
- [x] 3.2 ci.yml governance job 增加同名两步，job 名改为
  `OpenSpec + docs + actionlint + zizmor`；actionlint 与 zizmor 复跑 0 发现。

## 4. 门禁实测

- [x] 4.1 markdownlint：22 文件 0 问题（exit 0）。
- [x] 4.2 链接检查：257 文件 0 坏链（exit 0）。
- [x] 4.3 `uv run ruff check .` 通过；`ruff format --check .` 397 文件已格式化。
- [x] 4.4 `uv run mypy`：155 files 0 error（含新脚本与测试）。
- [x] 4.5 `uv run pytest`：903 passed、2 deselected，覆盖率 90.03% ≥ 89。
  注：本机 NO_PROXY 含 `[::1]` 时 httpx URL 解析用例失败，按 HANDOFF 口径
  设为 `localhost,127.0.0.1,127.0.0.0/8` 后全绿（环境差异，非代码回归）。
- [x] 4.6 契约快照：`uv run python -m siku.api.contract --refresh` 后
  `contracts/openapi.json` 无漂移。

## 5. 治理

- [x] 5.1 `openspec validate 2026-11-20-close-quality-gate-gaps --strict` 通过。
- [x] 5.2 `openspec validate --all --strict` 通过（含 8 个在途 change）。
- [x] 5.3 归档 `openspec/changes/archive/2026-11-20-close-quality-gate-gaps/`。

## 6. 不开的缺口（有理由，逐条登记）

- [x] 6.1 Rust CodeQL：GitHub CodeQL 无 Rust 语言支持，不加矩阵；替代链为
  clippy pedantic `-D warnings`（ci.yml desktop-shell）+
  `cargo audit`（security.yml rust-deps）+ `cargo deny check`（ci.yml），
  已在 design.md D7 与 `codeql.yml` 头注释登记。
- [x] 6.2 openspec/ 不纳入 markdownlint：结构由 `openspec validate --strict` 权威校验，
  归档件不回溯整改（design.md D1）。
- [x] 6.3 外链可达性不检查：需网络、受波动影响（proposal Non-goals）。
- [x] 6.4 `taplo`（TOML 格式）非本轮范围：现有 `check-toml` 覆盖语法；
  格式维度留待后续单独立项。
