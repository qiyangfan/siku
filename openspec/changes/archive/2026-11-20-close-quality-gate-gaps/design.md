# 设计：文档 lint、链接与锚点门禁

## Context

见 proposal.md。文档是治理三层（宪法/契约/ADR）的载体，但此前只有 `check-yaml`
一类结构校验与路径存在性断言，标题锚点、代码围栏语言、列表符号、行宽均无机器口径。

## Decisions

### D1 markdownlint 只守护人写文档

globs 取 `README.md`、`AGENTS.md`、`docs/**/*.md`、`benchmarks/README.md`、`ui/README.md`。
`openspec/**` 不纳入：主规格与 change 的结构由 `openspec validate --all --strict`
校验（Requirement/Scenario 形态），lint 规则与之部分冲突（例如 spec delta 以
`## ADDED Requirements` 开头，MD041 必然报错）。归档 change 是历史快照，回溯整改会让
归档件与当时评审证据脱节。

`docs/HANDOFF.md` 在 ignores 中：该文件本地维护、不入库，扫它会造成本机与 CI 口径不一致。

### D2 行宽 120，代码块与表格行豁免

中文技术散文以语义断句为准，不做强制折行；单行 120 列 ≈360 字节，常见编辑器仍可读。
代码块行宽由内容决定（命令、JSON），表格行宽由列数决定，两者豁免才有意义。
存量 12 处超宽长段已按语义重排（不裁内容）。

### D3 MD060（表格对齐）全局关闭

MD060 要求竖线按**显示宽度**逐列对齐：CJK 列与 ASCII 列混排时需按宽度补大量空格，
纯美观收益；全仓 157 行表格需要逐表重排。列式可读性由表头自证，渲染结果与对齐无关。
关闭理由写在配置文件注释中，README 文档地图表另加一条行内指令说明同类豁免。

### D4 MASTER.md 的行内豁免

`ui/design-system/MASTER.md` 的 token 表一行记录一组「用途/token/取值」，token 列是完整
CSS 变量族路径，折行会拆散三元组。该文件不在 globs 内；文件头保留一条
`markdownlint-disable MD013` 行内指令，作为「将来纳入即生效」的登记，而非全局关闭。

### D5 链接检查零网络，校验路径与锚点

脚本 `scripts/check_md_links.py`：

- 外部目标（含任意 scheme、协议相对 `//`）一律跳过，不做可达性探测——门禁禁止网络依赖。
- 路径解析：相对链接按来源文件目录、根相对链接按仓库根；目录链接落到其 `README.md`；
  百分号编码先解码（`a%20b.md`）；目标括号内的一层配对括号不被截断（`d(1).md`）。
- 锚点：目标为 `.md` 且带 `#片段` 时校验；片段按 GitHub slug 规则推导（小写、去标点、
  空格转连字符、同名标题依次 `-1`/`-2`），并接受标题内 `<a id>`/`name` 与 `{#id}`。
- 围栏代码块与行内代码先剔除（保持行号不变），示例里的链接不算真链接。
- `docs/HANDOFF.md` 默认排除，理由同 D1。

### D6 测试边界重划

全仓扫描归脚本（CI 与 pre-commit 直接执行）；`tests/test_docs_links.py` 改为解析器单测：
引用式定义、括号目标、slug 规则、同名去重、缺失文件与失效锚点、排除清单。

### D7 Rust 无 CodeQL，替代链已就位

GitHub CodeQL 不支持 Rust，故不加 Rust 语言矩阵（与 `codeql.yml` 头注释一致）。
桌面壳的替代覆盖：clippy pedantic `-D warnings`（含 build 模式数据流类告警）、
rustdoc `-D warnings`、`cargo audit`（RUSTSEC 公告，security.yml rust-deps）、
`cargo deny check`（许可证/来源/bans，ci.yml desktop-shell）。需求追踪与 TOML 维度
（`taplo`）不在本轮范围，理由登记在 review.md 遗留项。
