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

### mypy strict

`strict` 额外启用 `no_implicit_reexport` 等检查。暴露的 21 处 `attr-defined` 全是
"经 `model_supply` 隐式再导出"的导入；修法是让调用方改指定义模块
（`graph.providers` / `retrieve.errors` / `retrieve.models`），而不是给再导出加
`__all__` 扩大模块 API 面。

### pylint W/E 的排除项

W/E 全族在 src 开启，排除三类：W0718 与已否决的 ruff BLE001 同义；
W0613/W0621 来自 MCP 工具的统一签名（`vault`/`data_dir` 占位）与注册名遮蔽。
`with closing(conn) as c, c:` 会被 pylint 判为 W0124、又被 ruff SIM117 要求合并，
两侧互斥，故收敛为 `_transaction()`（显式提交/回滚 + finally 关闭），同时满足两套门禁。

### 文档链接检查：用 pytest 而不是 lychee

lychee/markdown-link-check 需要额外二进制或 Node 包，且默认走网络。文档链接都是
仓库内相对路径，用一个 40 行的 pytest 用例就能覆盖，零依赖、确定性、随既有
pytest 门禁一起执行。扫描面为 README/AGENTS/docs/openspec；代码块内的示例链接
先剥离，避免把示例当真实链接。HANDOFF.md 仅本地维护，显式排除以保持本地与 CI 同口径。

### 体积预算：size-limit 的取值

size-limit 14 默认报告 brotli 体积（不是 gzip），因此预算按 brotli 基线定：
JS 253.78 kB、CSS 33.02 kB，阈值取 265/35 kB（约 4%–6% 余量）。余量只吸收常规
小改动，新增依赖会突破阈值，强制显式调整预算而不是无声增长。按文件限定
`dist/assets/*.js|css`，未来代码分割后需重新评估单文件口径。

### 可选 extra 的审计口径

`ingest-pdf` 不在默认 env，pip-audit 扫不到。为此不安装 docling（会拉入 torch 系
数 GB），而是 `uv export --extra ingest-pdf` 导出完整锁定解析，再用
`pip-audit --no-deps -r` 按锁定版本查漏洞——审计不依赖本地安装。许可证白名单
不扩：该 extra 不进桌面产物、不由项目分发，grant 的 allowlist 只对发布面生效。
首跑即发现 soupsieve 3.0.3 的 CVE-2026-126190，升级 4.1.2 后清零。

### chunk_id 的边界歧义（属性测试首发现）

旧实现用 `\x1f` 分隔字段：`anchor="b\x1fc", text=""` 与 `anchor="b", text="c\x1f"`
拼接后完全相同，产生同 ID 不同内容。属性测试把它稳定复现后，改为每个字段
「8 字节长度前缀 + UTF-8 字节」再哈希，版本升 `v2`。chunk_id 是派生物，索引可重建，
因此不涉及数据迁移脚本。版本号写入 `index_meta.chunk_id_version`，`SqliteIndex.open`
在版本不一致或缺失时直接拒绝并提示 `siku index --rebuild`，避免旧 ID 被增量复用
后与新派生规则混在同一索引里；本地旧索引因此显式失败而非静默混用。

### 变异测试的范围与分数口径

全仓变异在 CI 时间上不可行，只对纯逻辑的 tokenizer 生成变异体、只跑对应测试文件；
96 个变异体、约 40 秒。分数 = (killed + timeout + segfault) / 有效变异体：
timeout 说明变异体让测试挂死，同样证明测试对行为敏感，且在慢机器上只会由
killed 变为 timeout，不会造成分数抖动。75% 阈值对当前 80.21% 留出噪声余量。

### 浏览器 E2E 用真实 serve 而不是 mock

Playwright 直接打开 `siku serve --with-ui`（临时 HOME/vault/data，fake 无需模型：
就绪态缺失只影响展示，不影响页面结构），同时验证静态资源挂载、同源 API 与
真实响应契约；mock 只能验证渲染，且会与后端 schema 漂移。axe 首跑即发现
资料库拖拽区 `aria-label` 与可见文本不一致（label-in-name），改为由内容命名后通过。

### 浏览器内核覆盖与未采纳项

桌面壳在 macOS 用 WKWebView、Linux 用 WebKitGTK、Windows 用 WebView2，因此
Playwright 同时跑 Chromium 与 WebKit（12 用例全过），而不是只测 Chromium。
Firefox/Gecko 不在任何发布目标内，不纳入。

官方 eslint-plugin-react 与 ESLint 10 不兼容（加载规则即 `contextOrFilename.getFilename
is not a function` 崩溃），改用 `@eslint-react/eslint-plugin`（peer 为 `eslint: *`，
实测在 ESLint 10 上正常）：首跑 3 条 warning，2 处 `dangerouslySetInnerHTML` 经
DOMPurify 清洗后定点抑制，1 处 `useState(new Set())` 改惰性初始化，现 0 问题。
视觉回归快照不引入：本地 macOS 与 CI Linux 的字体渲染差异会让快照长期
不稳定，维护成本高于收益。

### editorconfig-checker 的裁剪

ec 的 indent-size 会误伤 Python 续行对齐，max-line-length 会误伤长字符串/URL，
两者都已由 ruff/prettier/stylelint 按语言负责。保留编码、EOL、末尾换行与
行尾空白检查，避免与 formatter 的职责重叠。

### 跨平台与遗漏规则面

`.gitattributes` 用 `text=auto eol=lf` 把三端检出统一到 LF，避免 Windows 构建或
Windows 贡献者把 CRLF 带进仓库；二进制资产显式标记，防止 Git 做文本归一化。
`check-case-conflict` 针对的是 macOS（大小写不敏感）能建出两份、Linux CI 检出即
互相覆盖的文件，本地看不到问题，只能在提交前拦。

`T20` 是 AGENTS「禁止 print」的执法规则：src 已 0 命中，真正命中的 14 处全在
scripts/benchmarks——这些脚本的 stdout 是 CI 与人工读取的接口，改成 logging 会
改变输出契约，所以按目录豁免并写明原因，规则在 src 仍全量生效。

Windows Rust 代码（`#[cfg(windows)]` 的 Job Object 分支）目前只在 release 构建时
编译，PR 的 desktop-shell 只在 ubuntu 上跑。补 Windows 作业是正确方向，但本机
无 Windows runner，无法在提交前验证作业本身可跑；CI 账单阻塞期间新增未验证作业
风险大于收益，留作待验证项。

### cargo-deny 的边界

许可证 allowlist 只列实测出现的宽松许可证；`unmaintained` 取 cargo-deny 的
`workspace` 档——传递依赖的停止维护公告不阻断（tauri/zbus 链由上游统一升级），
漏洞公告仍全量阻断。Rust 覆盖率 36% 是回归下限，不是质量目标；pytest 300s
单用例超时只拦挂死，不压缩正常用例耗时。
