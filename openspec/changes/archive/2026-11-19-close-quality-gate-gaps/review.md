# 复核记录

## 门禁实测（归档前最终一轮）

| 门禁 | 命令 | 结果 |
|---|---|---|
| ruff lint | `uv run ruff check .` | All checks passed |
| ruff format | `uv run ruff format --check .` | 396 files formatted |
| pylint 结构 | 四个结构规则 | 10.00/10 |
| mypy | `uv run mypy` | 154 files，0 error |
| import-linter | `uv run lint-imports` | 3 kept, 0 broken |
| vulture | `uv run vulture` | 0 命中 |
| deptry | `uv run deptry src` | 0 问题 |
| zizmor | `uv run zizmor .github/workflows` | 0 发现 |
| actionlint | `actionlint` | 通过 |
| typos | `typos` | 0 命中 |
| shellcheck | `shellcheck ui/e2e/*.sh` | 0 告警 |
| pytest + 覆盖率 | `uv run pytest --cov=siku` | 901 passed，90.03%（阈值 89） |
| ESLint | `npx eslint .` | 0 error / 0 warning（含类型感知） |
| prettier | `npm run format:check` | 通过 |
| stylelint | `npm run lint:css` | 通过 |
| depcruise | `npm run lint:arch` | 0 违规（no-orphans 已升 error） |
| knip | `npm run lint:dead` | 通过 |
| jscpd | `npm run lint:dup` | 2.43%（TS+Python，阈值 5.2%） |
| vitest + 覆盖率 | `npm run test:cov` | 133 passed，80.18/75.44/82.8/79.91 |
| tsc | `npx tsc -b` | 0 error（含三个严格选项） |
| 浏览器 E2E + axe | `npm run test:e2e` | 12 passed（Chromium + WebKit） |
| mutation | `mutmut run` + 分数门禁 | 96 变异体，捕获 77（80.21%） |
| cargo-deny | `cargo deny check` | advisories/bans/licenses/sources 全 ok |
| openspec | `openspec validate --all --strict` | 通过 |

## 负向验收

- 规则本身均已在前批次做过负向验证（植入违规即失败）；vulture 60% 档实测报出
  15 条噪音、80% 档 0 条，确认扫描生效。
- E2E 失败现场：临时植入必然失败用例后，`ui/test-results/` 实际产出
  `trace.zip` 与 `test-failed-1.png`，与 CI 上传路径一致。
- 工具下载校验：6 处下载全部校验；篡改产物单字节后校验以 exit 1 失败。

## 遗留

- GitHub Actions 首跑仍受账号级账单锁定阻塞，required checks 待首个绿色运行后设置。
- ruff `D` 全族、commitlint、视觉回归快照等为明确 Non-goals（见 proposal）。
