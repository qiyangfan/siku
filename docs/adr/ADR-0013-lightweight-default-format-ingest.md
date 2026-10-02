# ADR-0013：轻量默认格式摄取与随包转换工具

- **状态**：已接受（2026-10-02 实施验收通过；证据见
  `openspec/changes/archive/2026-10-02-complete-desktop-format-ingest/review.md`）
- **日期**：2026-10-02
- **关联**：修订 ADR-0004 的默认 PDF 方案；遵守 ADR-0005 的 Extractor 边界与 ADR-0009 的无内置模型原则。
- **提案**：[complete-desktop-format-ingest](../../openspec/changes/complete-desktop-format-ingest/proposal.md)

## 问题

默认及冻结桌面运行时无法保证已展示的 PDF/Office 导入能力。全部安装重型 PDF extras 会带回 torch 与布局模型，既增加分发负担，也不能提供无下载的首次摄取。Word 的系统工具依赖则让“安装桌面包即可导入”依赖开发机环境。

## 决策

默认含文字 PDF 使用 pypdf；DOCX 沿用 pandoc，桌面构建携带固定版本的官方二进制；PPTX、XLSX/XLSM 沿用 python-pptx 与 openpyxl。轻量 Python 解析库进入默认运行时，torch 系引擎仍为 extras 且不进入默认桌面包。

格式工具只输出自持 Markdown 投影、source_hash 与结构锚点，不能改变存储 schema。PDF 保留原始页序；整份无文本时给出转换/OCR 指引。旧 `.doc/.ppt/.xls` 明确转换到现代格式，XLSM 不执行宏。已实现的 EPUB/HTML/Markdown 不重写。

pandoc 在构建期锁版本、平台与 SHA-256，随包保留许可及版权说明；冻结运行时以绝对资源路径调用，禁止 shell 拼接与运行时下载。开发/CLI 可沿用系统工具，缺工具时准确提示。UI/Tauri 不承载转换逻辑。

## 理由与代价

常用文本资料的本地抽取需要可靠分发，成熟轻量工具满足当前需求；原件与统一事实层保证后续可以重新抽取。扫描件 OCR 与复杂版面高保真没有当前交付依据，不值得为它们恢复模型管理与大体积分发。默认解析不承诺完整还原任意 PDF 布局，质量由实际投影与 golden set 验收。

相比依赖系统安装，随包转换工具增加固定构建资源和许可证维护；这直接换来桌面首次导入可用。保持一个默认包，不增加第二个模型 sidecar 或插件下载管理器。

## 验收及生效

2026-10-02 实施验收通过：默认安装经 pypdf/pandoc/python-pptx/openpyxl 完成四类
现代格式真实摄取（冻结 sidecar 在干净 PATH、无本机配置、代理黑洞环境下经
HTTP 冒烟，锚点与投影核对通过；扫描件 PDF 与旧二进制 Office 按稳定错误码
可行动拒绝）；三平台资源检查（`scripts/check_sidecar_artifacts.py`）进入 CI 与
release 门禁，产物 615 MiB（含随包 pandoc 3.11）且无 torch/模型权重；全量
pytest/ruff/UI 测试与构建通过。既有 golden set 的实端点基线沿用 2026-09-19
用户豁免口径（可按 benchmarks/README.md 随时补录）。索引和问答仍遵守 BYOK
前提，Release 禁用、签名条件和实机冒烟豁免保持；实现证据见归档 review.md。

## 上游依据

- [pypdf 文本提取与 OCR 边界](https://pypdf.readthedocs.io/en/latest/user/extract-text.html)
- [Pandoc 官方安装与二进制分发](https://pandoc.org/installing.html)
- [Pandoc 正式输入格式](https://pandoc.org/MANUAL.html)
