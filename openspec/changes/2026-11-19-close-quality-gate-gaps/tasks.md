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
