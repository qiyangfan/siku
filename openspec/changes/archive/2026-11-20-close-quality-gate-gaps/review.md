# 评审记录：文档 lint 与链接/锚点门禁

## 验证证据（本机实测，2026-11-20）

| 项 | 命令 | 结果 |
|---|---|---|
| markdownlint | `npx --yes markdownlint-cli2@0.24.1` | 22 files，0 issues |
| 链接与锚点 | `uv run python scripts/check_md_links.py` | 260 md，0 broken |
| 链接解析单测 | `uv run pytest tests/test_docs_links.py` | 4 passed |
| ruff | `uv run ruff check .` / `ruff format --check .` | 通过 / 400 files 已格式化 |
| mypy | `uv run mypy` | 155 files，0 error |
| pylint W/E | `uv run pylint --jobs=0 src/siku scripts` | 10.00 |
| vulture / deptry / import-linter | 三命令 | 0 命中 / 无依赖问题 / 3 kept 0 broken |
| pytest | `uv run pytest --cov=siku`（NO_PROXY 按 HANDOFF 口径） | 903 passed，2 deselected，覆盖率 90.03% |
| 契约快照 | `python -m siku.api.contract --refresh` + `git diff --exit-code` | 无漂移 |
| openspec | `validate 2026-11-20-… --strict` / `validate --all --strict` | 单件 valid / 19 passed 0 failed |
| 工作流 | `actionlint` / `uv run zizmor .github/workflows` | 通过 / No findings |

## 负向验证

- 临时树注入 `missing.md`、`../nope/x.md`、`#不存在`、坏引用式定义、`README.md#t`
  （锚点大小写不符）→ 脚本逐条报行号并 exit 1；围栏与行内代码中的同类写法不报。
- pre-commit 两 hook 实跑：`markdownlint`、`markdown-links` 均 Passed。

## 保留判断

- MD060（表格对齐）全局关闭：按 CJK 显示宽度补齐竖线的收益不抵 157 行表格的重排。
- openspec/ 不纳入 markdownlint：结构归 `openspec validate --strict`，归档件不回溯整改。
- MASTER.md 行内豁免 MD013：token 表三元组不可折行，文件已脱离 globs。
- 外链不做可达性检查：门禁零网络。

## 遗留

- 外部 CI 未绿（账号账单锁定，见 HANDOFF）；解锁后确认 governance job 首跑含两步新检查。
- `taplo`（TOML 格式维度）不在本轮：语法已由 `check-toml` 覆盖，格式单独立项。
