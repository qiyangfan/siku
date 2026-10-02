## Why

桌面资料库提供 PDF、Word、PPT、Excel 导入，但默认 sidecar 没有完整携带这些格式的运行时：PDF 依赖可选的重型抽取器，Word 依赖系统 pandoc，Office 解析库仍在 extras。用户安装桌面包后仍可能在导入时收到缺依赖错误，这与现有上手链路的承诺不一致。

直接把全部 PDF extras 打入桌面包会重新带回 torch 与模型下载，违反 ADR-0009 的分发边界。需要为普通文本文档补齐轻量、随包可用的默认抽取能力。

## What Changes

- 默认 PDF 采用成熟轻量解析器，保留页码锚点；不依赖 torch、OCR 模型或首次运行下载。
- DOCX 继续使用成熟转换工具，将平台对应的固定版本二进制随桌面包分发；PPTX、XLSX/XLSM 解析库进入默认可用运行时。
- 统一桌面、HTTP 与 CLI 的实际支持格式；扫描 PDF 与旧二进制 Office 格式给出可执行的转换提示。
- 在干净环境中验证冻结 sidecar 的真实摄取，而不只验证开发机依赖可用。
- 新增拟议 ADR-0013，修订 ADR-0004 的默认 PDF 选择，遵守 ADR-0005 与 ADR-0009 的轻量、可替换及不打包模型边界。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `ingest`：常用现代格式默认可抽取，支持范围及不可抽取错误准确可见。
- `desktop-shell`：桌面包携带常用格式所需的非模型运行时。

## Impact

涉及格式适配器、默认依赖、sidecar 构建资源、安装包检查、错误映射与格式说明；原件、Markdown 投影、`source_hash` 和页/幻灯片/工作表锚点契约保持。既有 EPUB/HTML/Markdown 能力不换引擎。

## Non-goals（不做清单）

- 不增加 OCR、扫描件识别、模型权重、torch 或运行时依赖下载器。
- 不自行实现 PDF 布局引擎、DOCX 到 Markdown 转换器或 Office 在线编辑预览。
- 不承诺默认解析器完整还原复杂 PDF 版面；错误必须真实，不能将空投影标成成功。
- 不增加旧 `.doc/.ppt/.xls` 解析链；提示用户转换为已有现代格式。
- 不增加云端抽取、不改 BYOK 检索语义、不为缺 embedding 静默退化排序。
- 不启用被禁用的 Release，不撤销既有 Windows/Linux 实机冒烟豁免，不启动签名/公证/自动更新。
- 不接支付能力；其他项目收款继续 Mock。
