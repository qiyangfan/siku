# 提案：收口质量门禁的可推进缺口

## Why

上一批次把 P0/P1 门禁全部接进 CI 后，逐项复测仍有“本地可跑但未落地”的缺口。
分五轮把可推进项全部收口，不留需要后续单独排期的悬项。

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
13. **typos 拼写门禁**：词表扩展 3 条（`datas`/`certifi`/`unparseable`）后 0 命中；
    pre-commit 与 CI governance 执行。
14. **ruff LOG + PLW**：3 处 `exc_info=True` 改为显式异常对象、1 处循环变量覆盖、
    4 处测试 lambda / `check` 参数修正；`BLE` 逐处核实为边界捕获，未启用。
15. **TS 三档收紧**：`noUncheckedIndexedAccess`、`exactOptionalPropertyTypes`、
    `noImplicitOverride` 开启，87 处错误清零。

16. **文档相对链接门禁**：新增 `tests/test_docs_links.py`，覆盖 README/AGENTS/
    docs/openspec；首跑发现 ADR-0013 指向已归档 change 的坏链并修复。
17. **pytest 严格档**：`--strict-markers --strict-config`，拼错 marker/配置键在
    收集期直接失败。
18. **Rust 检查面补齐**：clippy 加 `--all-targets`（暴露并清零测试代码 4 处
    pedantic 问题）；cargo-machete 查未使用依赖（当前 0）。
19. **前端体积与 extra 供应链**：size-limit 设 JS 265 kB / CSS 35 kB（brotli）
    体积预算；`ingest-pdf` extra 经 `uv export` + `pip-audit --no-deps` 审计，
    首跑发现 soupsieve CVE-2026-126190 并升级 4.1.2。
20. **print 执法**：ruff 启 `T20`（AGENTS 红线），src 0 命中；scripts/benchmarks
    的 stdout 是 CLI 接口，按目录豁免并注明。
21. **JSON 与大小写冲突**：pre-commit 增 `check-json`、`check-case-conflict`；
    14 个 JSON 全部有效。
22. **换行统一**：`.gitattributes` 全仓 `text=auto eol=lf` + 二进制标记。
23. **Rust 工具链固定**：`rust-toolchain.toml` 钉 1.98.1，CI 与 release 共用。
24. **PT011 / ASYNC / DTZ**：宽泛断言补 match（4 处），异步与时区规则启用，0 命中。
25. **hypothesis 属性测试**：6 组不变量；发现 chunk_id 字段边界歧义并修复
    （长度前缀 + `CHUNK_ID_VERSION=v2`）。
26. **pytest-randomly**：多轮随机顺序全量通过。
27. **mutmut**：tokenizer 96 个变异体，捕获 77（80.21%），每周 job + 75% 门禁。
28. **Playwright + axe**：真实 serve 下 6 条用例；修复资料库拖拽区 label-in-name。
29. **editorconfig-checker**：编码/换行/末尾换行入 pre-commit 与 CI。
30. **pre-commit 30 个 hook** 全绿。
31. **pylint 扩到 scripts**（10.00）；benchmarks 因 PEP 723 内联依赖不纳入。
32. **mypy `warn_unreachable`**：0 命中。
33. **rustdoc `-D warnings` 与 shellcheck** 进 CI 与 pre-commit，0 告警。
34. **Playwright 增 WebKit**（桌面 WKWebView/WebKitGTK）：12 用例全过；
      pre-commit 共 **32 个 hook**。

附带修复：`test_api_cli` 的图 JSON 对照用例显式使用 `tmp_path`，消除对本地
`vault/`、`data/` 残留产物的隐式依赖。

## 关键数字

- mypy：**151 files** 通过（src + tests + scripts + benchmarks）。
- ESLint：类型感知开启后 0 error / 0 warning（开启前 49 error + 9 warning）。
- vulture：0 命中；deptry：0 问题；depcruise：0 违规；zizmor：0 发现。
- UI 覆盖率：语句 80.16 / 分支 75.44 / 函数 82.74 / 行 79.89（阈值 79/75/81/79）。
- jscpd：TS 4.67% + Python 0.34%，合并 **2.43%**（阈值 5.2%）。
- mypy `strict`：35 处清零；clippy `pedantic`：21 处清零；pylint W/E（src）10.00。
- Rust 覆盖率回归下限 36%（实测 36.51%）；pytest 单用例 300s 硬超时。
- 文档链接：240 个 md 0 坏链（修复 1 处）；Rust 未使用依赖 0；体积 JS 253.7 kB /
  CSS 33.02 kB（阈值 265/35）；extra 审计 202 包 0 漏洞；pre-commit 30 个 hook。
- pytest **898 passed**（随机顺序）、mypy **154 files**、vitest 133、Playwright **12 passed**
  （Chromium + WebKit）、变异分数 **80.21%**（96 个变异体）、pre-commit 32 hook。

## Non-goals

- 不引入 commitlint / markdownlint / taplo / yamllint（无根 Node 工具链；YAML/TOML
  已有语法校验）。
- 浏览器 E2E 覆盖 Chromium + WebKit、WCAG A/AA，不覆盖移动端视口与 Firefox。
- 不引入官方 eslint-plugin-react：与 ESLint 10 不兼容；React 规则由
  `@eslint-react/eslint-plugin` 提供。
- 不引入视觉回归快照：本地 macOS 与 CI Linux 渲染差异会导致长期不稳定。
- 不启用 ruff `D` 全族（缺 152 条 docstring，且 D400/D415 与中文句号约定冲突）。
- 不启用 `max-lines-per-function`（默认 50）：实测 20 个生产函数超限，前五为
  292–498 行的视图组件；启用等价于重写全部视图，模块级 `max-lines`（1000）与
  `complexity`（20）已覆盖结构风险。
- mutation testing 只覆盖 tokenizer 一个纯逻辑模块并按周运行；全仓变异在
  CI 时间上仍不可行。
- hypothesis 只用于纯函数不变量（6 组），不做全仓强制属性测试。
- 不扩 `ingest-pdf` extra 的许可证 allowlist：该 extra 不随桌面产物分发，
  grant 只对发布面生效；漏洞审计仍覆盖。

## 受影响决策

只引用、不修改：ADR-0008（门禁沿用既有 job，不新增矩阵桶）。`skip_specs: true`。

## Impact

- `pyproject.toml`（mypy/deptry/vulture 配置、starlette 依赖、dev 依赖）
- `.pre-commit-config.yaml`、`.github/workflows/ci.yml`
- `tests/` 22 个文件的导入与类型标注
- `ui/eslint.config.js`、`ui/src/*`（API 错误类、effect 结构、测试辅助）
- `ui/.dependency-cruiser.cjs`、`ui/vite.config.ts`、`ui/src-tauri/deny.toml`
