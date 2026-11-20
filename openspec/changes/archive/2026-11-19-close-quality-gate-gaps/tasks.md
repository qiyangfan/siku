# 任务清单

## 1. mypy 覆盖 tests

- [x] 1.1 `explicit_package_bases` + `files = ["src", "tests"]`，`mypy_path = ["src"]`。
- [x] 1.2 22 个测试文件统一 `tests.xxx` 包限定导入（pytest `pythonpath="."` 口径一致）。
- [x] 1.3 修完 22 处类型错误（MCP 文本块、IndexReport.rebuilt、生成器返回、tuple/list、
      未注解函数、任意值）。
- [x] 1.4 验证：`uv run mypy` 退出 0（144 files）。

## 2. ESLint 类型感知

- [x] 2.1 `recommendedTypeChecked` + `projectService`，仅 TS/TSX 生效。
- [x] 2.2 生产代码：`ApiHttpError`、floating promise `void`、删除多余断言。
- [x] 2.3 测试代码：`requestUrl` / `requestBody` / `parseSettingsBody` 统一取值；
      unbound-method 改为局部 mock 引用。
- [x] 2.4 验证：`npx eslint .` 0 error / 0 warning。

## 3. set-state-in-effect

- [x] 3.1 取数 effect 落到异步续体（App/BrowseView/GraphView/LibraryView/WikiView）。
- [x] 3.2 建议区复位改渲染期派生；问答聚焦改请求计数 + 已处理 ref。
- [x] 3.3 规则回推荐集默认（error），验证 0 告警；133 个 UI 测试通过。

## 4. Python 静态门禁

- [x] 4.1 vulture `min_confidence=80` 接入 pyproject / CI / pre-commit，0 命中。
- [x] 4.2 deptry 接入：`starlette` 升为直接依赖，2 条例外注明原因，0 问题。

## 5. 其余收口

- [x] 5.1 depcruise `no-orphans` 排除 `vite-env.d.ts` 并升为 error。
- [x] 5.2 pre-commit 增加 openspec strict 与 actionlint 两个 hook，均实跑通过。
- [x] 5.3 `test_api_cli` 用 `tmp_path` 隔离 vault/data，消除本地数据依赖。

## 6. 收口

- [x] 6.1 全量 pytest + 覆盖率阈值通过。
- [x] 6.2 openspec validate --all --strict、actionlint 通过。
- [x] 6.3 HANDOFF 回写。

## 7. 二轮复测补口

- [x] 7.1 mypy 纳入 scripts/benchmarks，修 `smoke_clean_env.py` 的 save(Path)；
      151 files 通过。
- [x] 7.2 jscpd 增加 Python 扫描，合并重复率 2.43% ≤ 5.2%。
- [x] 7.3 npm audit 去掉 `--omit=dev`，全量 0 漏洞。
- [x] 7.4 `filterwarnings = ["error"]`；修 mutex 测试 Popen stdout 未关闭。
- [x] 7.5 zizmor 0 发现：39 处 action 固定 SHA、按 job 最小权限、发布缓存关闭。
- [x] 7.6 zizmor 进 CI governance + pre-commit（dev 依赖 `zizmor>=1.32`）。
- [x] 7.7 typos 拼写门禁：8 条命中按词表扩展（PyInstaller `datas`、`certifi`、
      `unparseable`）清零；pre-commit + CI governance 接入。
- [x] 7.8 ruff 启 `LOG` + `PLW`：修 `exc_info=True`→显式异常对象 3 处、循环变量覆盖
      1 处、测试 lambda/check 参数 4 处；`BLE` 经逐处核实全为边界捕获，不启用。
- [x] 7.9 TS 三档收紧：`noUncheckedIndexedAccess` + `exactOptionalPropertyTypes` +
      `noImplicitOverride`，87 处错误清零（生产 13 / 测试 74）。
- [x] 7.10 `max-lines-per-function`（默认 50）：实测 20 个生产函数超限，前五为 292–498
      行的视图组件；启用等价于重写全部视图，属结构重构而非门禁修复，明确不启用。

## 8. 三轮全量收口

- [x] 8.1 mypy `strict = true`：35 处错误清零（21 处隐式再导出、8 处无用 ignore、
      6 处泛型参数），导入改指定义模块而非经 `model_supply` 再导出。
- [x] 8.2 clippy pedantic：21 处错误 + `build.rs` 分号清零；CI 与 pre-commit 均启用
      `-D warnings -W clippy::pedantic`，pre-commit 另接 rustfmt。
- [x] 8.3 前端门禁进 pre-commit（prettier / eslint / stylelint 全量）；新增
      `eslint-plugin-testing-library` + `@vitest/eslint-plugin`，26 处测试侧问题清零，
      vitest 开 `globals` 以启用 RTL 自动卸载。
- [x] 8.4 pylint W/E 只在 src 开启（tests 保持 4 条结构规则）：`with A as c, c` 21 处
      收敛为 `_transaction()`；`_JobObserver` 跨实例私有访问改走 manager 方法；
      2 处无意义 `except ...: raise` 删除；10.00 分。
- [x] 8.5 `cargo-deny`（许可证 allowlist、unmaintained 仅工作区级阻断、bans/sources）、
      Rust 覆盖率回归下限 36%（实测 36.51%）、pytest 300s 单用例硬超时。

## 9. 四轮补口

- [x] 9.1 文档相对链接门禁：新增 `tests/test_docs_links.py`（扫 README/AGENTS/docs/openspec），
      修复 ADR-0013 指向已归档 change 的坏链；负向验证单条坏链即失败。
- [x] 9.2 pytest 严格档：`--strict-markers --strict-config`；未注册 marker 在收集期直接报错。
- [x] 9.3 clippy 加 `--all-targets`：暴露测试代码 4 处 pedantic 问题（2 处 let-else、
      2 处 `as i32`），清零；fmt/clippy/test 11 通过。
- [x] 9.4 cargo-machete 接入 CI 与 pre-commit；当前 0 未使用依赖。
- [x] 9.5 前端产物体积预算 size-limit：JS 265 kB / CSS 35 kB（brotli），
      基线 253.78 / 33.02 kB；负向验证 1 kB 阈值退出码 1。
- [x] 9.6 `ingest-pdf` extra 漏洞审计：`uv export --extra` + `pip-audit --no-deps -r`
      不安装 torch 系；发现 soupsieve 3.0.3（CVE-2026-126190）并升级 4.1.2，
      复测 0 漏洞。许可证白名单不扩：该 extra 不随桌面产物分发。
- [x] 9.7 ruff 启 `T20`：落实 AGENTS「禁止 print」；src 0 命中，
      scripts/benchmarks 的 stdout 是 CLI 接口，按文件豁免并注明原因。
- [x] 9.8 pre-commit 增加 `check-json` 与 `check-case-conflict`：14 个 JSON 全部有效；
      大小写冲突在 macOS 本地不可见、到 Linux CI 才炸，须提交前拦截。
- [x] 9.9 `.gitattributes`：全仓 `text=auto eol=lf` + 7 类二进制标记，
      统一 macOS 开发 / Linux CI / Windows 发布三端检出。

## 10. 五轮补口：测试深度与跨端一致

- [x] 10.1 Rust 工具链固定 1.98.1（rust-toolchain.toml 含 fmt/clippy/llvm-tools），
      CI 与 release 改用 `rustup install`，不再跟随 stable 漂移。
- [x] 10.2 PT011 进 ruff select：4 处宽泛断言补 `match`，frozen dataclass 改断言
      `FrozenInstanceError`；移除 1 处 noqa。
- [x] 10.3 ruff 启 `ASYNC`、`DTZ`：全仓 0 命中。
- [x] 10.4 hypothesis 属性测试 6 组：发现并修复 chunk_id 字段边界歧义
      （分隔符方案下 `anchor="b\x1fc", text=""` 与 `anchor="b", text="c\x1f"` 同 ID），
      改为 8 字节长度前缀并升 `CHUNK_ID_VERSION=v2`；index_meta 记录版本，
      `open` 不匹配即拒绝并提示 `--rebuild`（3 条回归测试）。
- [x] 10.5 pytest-randomly 启用：多轮随机顺序全量 898 passed。
- [x] 10.6 mutmut 变异测试：tokenizer 96 个变异体，捕获 77（80.21%，timeout 计捕获），
      每周 workflow + 75% 分数门禁。
- [x] 10.7 Playwright + axe：真实 `serve --with-ui` 下 6 条用例（问答页 + 5 视图），
      修复资料库拖拽区 label-in-name 违规；vitest 收窄到 src 避免误收 e2e。
- [x] 10.8 editorconfig-checker：pre-commit 系统 hook + CI 下载固定版本；
      缩进/行长交由 formatter，ec 只查编码、换行、末尾换行。
- [x] 10.9 pylint W/E 扩到 scripts（10.00）；benchmarks 的 PEP 723 内联依赖不在
      env 中、会被误报 import-error，明确不纳入。
- [x] 10.10 mypy 启 `warn_unreachable`：154 files 0 命中。
- [x] 10.11 rustdoc `-D warnings` 进 CI 与 pre-commit：0 告警。
- [x] 10.12 shellcheck 进 CI 与 pre-commit：现有 `ui/e2e/serve-app.sh` 0 告警。
- [x] 10.13 Playwright 增 WebKit 项目（桌面 WKWebView / WebKitGTK）：**12 passed**。
- [x] 10.14 pre-commit **32 个 hook** 全绿。
- [x] 10.15 React 规则改用 `@eslint-react/eslint-plugin`（兼容 ESLint 10；官方
      eslint-plugin-react 崩溃）：首跑 3 条 warning 全部收敛，eslint 0 问题。
