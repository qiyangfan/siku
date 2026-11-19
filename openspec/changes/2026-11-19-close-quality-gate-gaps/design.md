# 设计：门禁缺口收口

## 关键取舍

### mypy 覆盖 tests：统一导入名而不是 dual-path

tests 同时存在 `from tests.xxx import` 与顶层 `from fakes import` 两种写法，mypy 需要
唯一模块名。备选：给 `tests/` 加 `__init__.py`——会改变 pytest 的 prepend 导入行为，
使 e2e 目录的 `fake_channels` 顶层导入失效。选定方案：只改导入为 `tests.xxx`，
pytest 的 `pythonpath="."` 与 mypy 的 `explicit_package_bases` 口径一致。

### 类型感知 ESLint：按文件域启用

`projectService` 只对 TS/TSX 开启；`eslint.config.js` / `.dependency-cruiser.cjs`
不进 tsconfig，全局开启会产生 “not found by project service” 解析错误。

### `set-state-in-effect`

- 取数 effect：把调用放进 `Promise.resolve().then(...)` 续体，使 setState 不在 commit
  同步阶段发生；加载序号与清理逻辑不变。
- 建议区复位：view/health 变化时在**渲染期**比对派生 key 并复位，属 React 官方
  “adjusting state when props change” 模式，effect 只负责取数。
- 问答聚焦：布尔标记 + effect 内清零改为请求计数 + `handledFocusRequestRef`，
  effect 内只做 DOM 副作用。

### vulture 阈值

80% 命中 0 条；60% 档把 pydantic `model_config`、MCP 工具注册函数等动态引用误报为
死代码（实测 15 条），因此固定 80，不自建白名单。

### deptry 例外

`python-multipart` 无 Python import（FastAPI multipart 解析运行时依赖）；
`docling` 只在可选 extra 内动态导入。二者用 `per_rule_ignores` 注明，而非引入
假导入点。`starlette` 是直接 import，按 DEP003 正确做法提升为一等依赖。

### zizmor 与工作流硬化

- **SHA 固定**：全部 action 从 tag 改为 commit SHA，行尾保留版本注释；更新交由
  既有 Dependabot `github-actions` 生态（会同时改写 SHA 与注释）。
- **最小权限**：release.yml 顶层降为 `contents: read`，只有发布作业声明
  `contents: write`；ci.yml 顶层补 `contents: read`。
- **缓存投毒**：发布工作流关闭 `setup-uv` 与 `setup-node` 的缓存——带写权限的
  job 使用可写缓存存在投毒面；CI 普通作业保留缓存。
- **凭据持久化**：所有 checkout 加 `persist-credentials: false`，避免 token 留在
  `.git/config`。

### pytest 告警与不可忽略异常

`filterwarnings = ["error"]` 开启后暴露一处 Popen stdout 未显式关闭、由 GC 关闭时
抛出的 unraisable。修法是在 finally 显式 `close()`，不放宽过滤规则。

### 函数长度规则：不照搬

`max-lines-per-function` 默认 50 行。实测生产代码 20 个函数超限，前五为
LibraryView(498)、SettingsView(434)、App(380)、GraphView(371)、WikiView(336)，
全部是视图组件的 JSX 渲染函数。启用该阈值等价于把每个视图拆成 5–10 个子组件，
属于架构重构而非门禁修复，且会产生大量无语义阈值。保持模块级 `max-lines` 1000 +
`complexity` 20 作为结构门禁。

### TS 严格档

三个编译器选项是缺陷类而非风格类：`noUncheckedIndexedAccess` 暴露 56 处
可能为 undefined 的索引、`exactOptionalPropertyTypes` 3 处可选属性赋值、
`noImplicitOverride` 0 处。测试侧用 `groupAt`/`tokenValue` 等显式守卫替代
非空断言，保持"找不到就抛错"的测试失败语义。

## 风险

- 测试导入重写涉及 22 个文件，靠全量 pytest 375 秒回归兜底。
- ESLint 类型感知对 mock 取值的约束，通过共享测试辅助收口，不放松规则。
