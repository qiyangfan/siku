# 复核记录

## 门禁实测

| 门禁 | 命令 | 结果 |
|---|---|---|
| ruff lint | `uv run ruff check .` | All checks passed |
| ruff format | `uv run ruff format --check .` | 389 files formatted |
| pylint 结构 | 四个结构规则 | 10.00/10 |
| mypy | `uv run mypy` | 151 files，0 error |
| import-linter | `uv run lint-imports` | 3 kept, 0 broken |
| vulture | `uv run vulture` | 0 命中 |
| deptry | `uv run deptry src` | 0 问题 |
| zizmor | `uv run zizmor .github/workflows` | 0 发现 |
| pytest + 覆盖率 | `uv run pytest --cov=siku` | 全量通过，阈值 89 守住 |
| ESLint | `npx eslint .` | 0 error / 0 warning（含类型感知） |
| prettier | `npm run format:check` | 通过 |
| stylelint | `npm run lint:css` | 通过 |
| depcruise | `npm run lint:arch` | 0 违规（no-orphans 已升 error） |
| knip | `npm run lint:dead` | 通过 |
| jscpd | `npm run lint:dup` | 2.43%（TS+Python，阈值 5.2%） |
| vitest + 覆盖率 | `npm run test:cov` | 133 passed，80.16/75.44/82.74/79.89 |
| tsc | `npx tsc -b` | 通过 |
| openspec | `openspec validate --all --strict` | 通过 |
| actionlint | `actionlint` | 通过 |

## 负向验收

- 规则本身均已在前批次做过负向验证（植入违规即失败）；本批次新增的 vulture 在 60%
  档实测能报出 15 条（说明扫描生效），80% 档为 0。
- depcruise 由 1 warn 收敛后，违规计数为 0，规则为 error。

## 遗留

- 未提交、未推送；CI 首跑仍受 GitHub 账号账单锁定阻塞，7+1 个 change 保持 active。
- ruff `D` 全族、axe/Playwright、commitlint 等为明确 Non-goals。
