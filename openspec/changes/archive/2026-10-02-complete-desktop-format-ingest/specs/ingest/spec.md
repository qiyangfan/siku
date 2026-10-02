## MODIFIED Requirements

### Requirement: 生成本地 Markdown 事实层

系统 SHALL 将原件复制到 `vault/attachments/`，并将 Markdown 投影写入 `vault/notes/`；投影 SHALL 包含 `source_hash`、源文件名、格式适配器和结构锚点。默认安装 SHALL 支持含可抽取文本的 PDF、DOCX、PPTX、XLSX、XLSM 及已有 EPUB/HTML/Markdown；各入口 SHALL 如实表达同一支持范围。无法抽取的文件 SHALL 返回可行动的失败，SHALL NOT 将空投影标为成功；扫描件 SHALL 提示先转换为含文字的文档，旧二进制 Office 格式 SHALL 提示转换为对应现代格式。

#### Scenario: 四类闸门格式摄取

- **GIVEN** 一个含可抽取文本的 PDF、DOCX、PPTX 或 XLSX 原件
- **WHEN** 用户通过默认安装执行摄取
- **THEN** 系统在 attachments 保留原件，在 notes 生成可读 Markdown 投影，无需另装该格式的解析依赖

#### Scenario: 结构锚点保留

- **GIVEN** 抽取结果包含页、slide 或 sheet 边界
- **WHEN** 系统生成投影
- **THEN** 投影为对应块保留 `page:N`、`slide:N` 或 `sheet:NAME` 锚点
- **AND** PDF 中间空白页不改变后续页面的原始页号

#### Scenario: 无文本 PDF 如实失败

- **GIVEN** PDF 没有可抽取文本
- **WHEN** 用户摄取该文件
- **THEN** 系统报告需要先识别或转换为含文字文档，不生成成功的空投影，不自动下载识别模型

#### Scenario: 旧 Office 格式有转换指引

- **GIVEN** 用户选择旧二进制 `.doc`、`.ppt` 或 `.xls`
- **WHEN** 系统校验或尝试摄取
- **THEN** 明确说明需转换为 DOCX、PPTX 或 XLSX，不声称格式已支持或把缺依赖隐藏为成功

#### Scenario: 已有轻量格式继续可用

- **GIVEN** 用户导入 EPUB、HTML、Markdown 或 XLSM
- **WHEN** 执行摄取
- **THEN** 既有正文抽取与结构锚点能力保留，XLSM 不执行宏

## ADDED Requirements

### Requirement: 默认格式抽取无需模型端点

默认格式的解析和 Markdown 投影 SHALL 可在本地完成，SHALL NOT 依赖模型权重、识别服务或首次运行的依赖下载。后续索引、图谱、Wiki 与问答 SHALL 保持既有端点配置及质量契约，不因本要求静默降低检索能力。

#### Scenario: 离线抽取与索引前提分开

- **GIVEN** 默认格式运行时已安装，用户尚未配置模型端点且网络不可达
- **WHEN** 用户执行文档解析与投影阶段
- **THEN** 格式抽取可以完成；需要模型端点的后续阶段按既有规则明确报告配置前提，不伪装完整问答已可用
