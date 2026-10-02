# 提案评审

- 状态：proposal/design/tasks/spec delta 已编写；ADR-0013 为拟议，默认解析器与桌面包尚未变更。
- 必要性：导入入口存在而默认/冻结运行时缺格式依赖，是已承诺上手链路的实质缺口。
- 单一裁决：复用轻量 PDF 解析器与已有成熟 Office 工具；不以重新打包 torch/模型解决普通文档导入。
- 支持边界：现代格式、含文字 PDF；扫描件与旧二进制格式提供转换指引，不谎报成功。
- 复用核对：Extractor、facts schema、原件与锚点沿用；既有 EPUB/HTML/Markdown、XLSM 与 BYOK 语义保留。
- 交付边界：冻结包干净环境验证属于实施门禁，Release 与既有平台豁免不变；没有执行编译或业务测试。
- 提案严格校验结果记录于本轮 HANDOFF。

## 本轮验证（2026-10-02）

- 本件及本轮全部 7 件 change 的 OpenSpec 严格校验通过；对应 ingest、desktop-shell 的临时预合并规格严格校验通过，未写入主规格。
- MODIFIED 原 Requirement/Scenario 名称保留检查、局部文档链接、任务未勾选、文档变更范围及 `git diff --check` 均通过。
- 只读方案复核已完成，必要修正写回设计、规格和实施回归；收款继续 Mock。
- 本轮没有业务代码、依赖或迁移变更，未运行编译、业务测试、UI 实机或打包验收，不把提案通过记成实现完成。

## 实施验证（2026-10-02）

- 代码：`PdfExtractor` 改为 pypdf 公开文本提取（保留原始页序锚点、整份无文本
  按可行动失败、加密/损坏分型）；`python-pptx`/`openpyxl`/`pypdf` 进核心依赖，
  `ingest-office` extras 移除（docling 重引擎保留 `ingest-pdf` extras，不入默认）。
  pandoc 运行时定位（`extractors/pandoc_runtime.py`）：冻结随包绝对路径优先、
  开发回退系统 PATH、参数数组 + 120s 超时 + 无 shell。
- 随包资源：`scripts/resources/pandoc.json` 锁定 pandoc 3.11 四平台 URL/SHA-256
  （官方 release 实测下载校验）与 GPL 版权说明（`pandoc-COPYRIGHT.txt` 入仓）；
  `scripts/build_sidecar.py` 构建期下载校验并收集到 `_internal/pandoc/bin/`；
  `scripts/check_sidecar_artifacts.py` 产物门禁（资源齐备/魔数架构核对/无 torch/
  BUILD_INFO 轻量运行时记录 + `--probe` 冻结可执行探针）已接入 ci.yml 三平台矩阵
  与 release.yml。
- 错误契约：新增稳定码 `scanned_pdf_no_text` / `legacy_office_format` /
  `encrypted_document` / `corrupt_document` / `converter_unavailable`（422/503），
  CLI 与 HTTP 双面同源；旧 `.doc/.ppt/.xls` 单文件摄取给转换指引，目录模式保持
  既有忽略口径。
- 测试：新增/改写 `test_ingest_extractors.py`（reportlab 中英文 PDF、空白中页、
  无文本/加密/损坏、真实 DOCX/PPTX/XLSX/XLSM 夹具）、`test_ingest_pipeline.py`
  （旧格式拒绝、类型化错误翻译、默认注册表 PDF 端到端）、`test_pandoc_runtime.py`、
  `test_sidecar_artifacts.py`；全量 pytest 796 通过、ruff check/format 干净。
- 冻结冒烟（3.3）：本机真实构建 sidecar（615 MiB，无 torch/模型），干净 PATH
  （`/usr/bin:/bin`）、隔离 HOME（无 config.toml）、代理指向黑洞下经 HTTP 摄取
  四类文档成功且锚点核对（pdf page:1/page:3、docx、pptx slide:1、xlsx sheet），
  扫描件/旧格式按稳定码拒绝——`scripts/smoke_clean_env.py` 全绿。
- 投影质量（3.4 部分）：`benchmarks/corpus` 四文档以新默认引擎重抽，PDF 双页锚点、
  PPTX 三 slide、XLSX 双 sheet、DOCX 标题结构核对可读；golden set 实端点基线沿用
  2026-09-19 用户豁免（fake-provider 评测链路由测试覆盖），未调整任何基线。
- HTTP→资料库状态：/api/ingest 与资料库冒烟经 `smoke_clean_env.py` 与既有
  `test_api_library.py` 覆盖；OpenSpec 严格校验 2/2 通过。
- 既有口径顺带修复：`test_graph_cli.py` 增加模块级环境隔离 fixture——宿主机
  `DASHSCOPE_API_KEY` 等环境变量此前会使 wiki 身份测试假红（基线复现确认非本轮
  引入，属测试隔离缺陷，按应改尽改处理）。
- Release 禁用与 Windows/Linux 实机冒烟豁免保持；本 ADR-0013 已转「已接受」。

## 第二轮验证补充（2026-10-02）

- 全量回归：pytest **801 通过**（含评审第二轮修复回归）、ruff check/format 干净、
  UI vitest 114 / tsc / eslint / vite build 通过、OpenSpec 主规格 8/8。
- UI 验收（3.5）：375/768/1280 三档视口程序化溢出/叠压检查全部干净（仅隐藏
  file input 的既有裁剪）；375 视觉走查通过（移除操作按钮宽度按内容收敛后）。
  「亮暗两态」不适用：产品 `forceColorScheme="light"`，暗色模式从未实现——
  任务文本的该项预设与产品现状不符，如实登记为待 owner 决策项（是否补暗色主题）。
- 评审结论：change 1 范围（pypdf/pandoc/错误分型/构建脚本/契约）无确认缺陷。
