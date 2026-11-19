# 提案：收口质量门禁最后 7 处可推进缺口

## Why

上一批次把 P0/P1 门禁全部接进 CI 后，逐项复测发现仍有 7 处“本地可跑但未落地”的缺口。
本次全部收口，不留需要后续单独排期的悬项。

## What Changes

1. **mypy 覆盖 tests**：`files = ["src", "tests"]` + `explicit_package_bases`；
   tests 内 `fakes`/`graph_fakes` 等顶层导入统一为 `tests.xxx` 包限定（22 个文件），
   修完 22 处真实类型错误（MCP 结果取文本、IndexReport.rebuilt、生成器返回类型、
   tuple/list 不一致、任意值断言等）。
2. **ESLint 类型感知**：`recommendedTypeChecked` + `projectService`，仅作用于 TS/TSX；
   修掉 46 处错误（no-base-to-string、no-unsafe-*、no-floating-promises、
   only-throw-error、unbound-method 等），测试取 URL/请求体统一走
   `requestUrl`/`requestBody`/`parseSettingsBody` 辅助；`api.ts` 改用 `ApiHttpError`
   继承 `Error` 并保留 `code` 契约。
3. **`set-state-in-effect` 升为 error**：9 处清零。取数类 effect 落到异步续体；
   建议区复位改为渲染期派生；问答聚焦改为请求计数 + 已处理 ref，不再在 effect 内
   同步 setState。
4. **vulture 死代码门禁**：`min_confidence = 80`（60% 档有 15 条框架动态引用误报），
   进 CI 与 pre-commit；实测当前 0 命中。
5. **deptry 依赖卫生**：`starlette` 直接 import 提升为一等依赖；`python-multipart`
   （FastAPI 运行时按需使用）与 `docling`（可选 extra 动态导入）按规则注明例外。
6. **depcruise 清零**：`vite-env.d.ts` 属三斜线类型引用文件，`no-orphans` 排除该文件
   并升为 error。
7. **治理检查本地化**：pre-commit 增加 `openspec validate --all --strict`
   （node hook）与 `actionlint`（system hook），提交时即拦，不再只依赖 CI。
8. **mypy 纳入 scripts/benchmarks**：`files` 扩为四类路径，修 1 处
   `Presentation.save(Path)`；检查面 151 files。
9. **PMD CPD 的 Python 侧**：jscpd 同时扫 `ui/src` 与仓库 `src/`（Python 重复率
   0.34%，合并后 2.43%）。
10. **JS 依赖审计含 dev**：security.yml 去掉 `--omit=dev`，与 Python 侧审计整个
    venv 的口径对齐（当前全量 0 漏洞）。
11. **pytest 告警即失败**：`filterwarnings = ["error"]`；同时修掉一处 Popen stdout
    未显式关闭导致的 unraisable（原先被 GC 关闭时抛出）。
12. **zizmor 工作流安全审计**：初始 39 unpinned-uses / 9 excessive-permissions /
    2 cache-poisoning 全部清零——action 固定 commit SHA、按 job 最小权限
    （release 仅发布作业持写权限）、发布工作流关闭包管理器与 uv 缓存；zizmor 进
    CI governance 与 pre-commit，dev 依赖锁定版本。

附带修复：`test_api_cli` 的图 JSON 对照用例显式使用 `tmp_path`，消除对本地
`vault/`、`data/` 残留产物的隐式依赖。

## 关键数字

- mypy：**151 files** 通过（src + tests + scripts + benchmarks）。
- ESLint：类型感知开启后 0 error / 0 warning（开启前 49 error + 9 warning）。
- vulture：0 命中；deptry：0 问题；depcruise：0 违规；zizmor：0 发现。
- UI 覆盖率：语句 80.16 / 分支 75.44 / 函数 82.74 / 行 79.89（阈值 79/75/81/79）。
- jscpd：TS 4.67% + Python 0.34%，合并 **2.43%**（阈值 5.2%）。

## Non-goals

- 不引入 commitlint / markdownlint / taplo / yamllint（无根 Node 工具链；YAML/TOML
  已有语法校验）。
- 不引入 axe/Playwright 运行时无障碍断言（静态 jsx-a11y 已覆盖可判定面）。
- 不启用 ruff `D` 全族（缺 152 条 docstring，且 D400/D415 与中文句号约定冲突）。

## 受影响决策

只引用、不修改：ADR-0008（门禁沿用既有 job，不新增矩阵桶）。`skip_specs: true`。

## Impact

- `pyproject.toml`（mypy/deptry/vulture 配置、starlette 依赖、dev 依赖）
- `.pre-commit-config.yaml`、`.github/workflows/ci.yml`
- `tests/` 22 个文件的导入与类型标注
- `ui/eslint.config.js`、`ui/src/*`（API 错误类、effect 结构、测试辅助）
- `ui/.dependency-cruiser.cjs`
