# web-ui Specification

## Purpose
提供一个只依赖 localhost HTTP API 的最小对话界面，让用户向本地知识库提问并查看带来源
依据的回答；界面不承载检索、提示词或回答校验逻辑。

## Requirements

### Requirement: 支持提交单轮问题并展示回答

界面 SHALL 提供问题输入和提交操作，通过 `POST /api/ask` 发送单轮问题；成功时 SHALL 展示
回答、模型身份和可展开的来源引用。界面 SHALL 在请求完成前阻止重复提交。

#### Scenario: 展示带引用的回答

- **GIVEN** API 返回有效答案与引用
- **WHEN** 用户提交问题
- **THEN** 界面展示答案正文，并可展开每条引用查看来源名、路径、锚点和证据片段

#### Scenario: 展示证据不足

- **GIVEN** API 返回 `insufficient_evidence=true`
- **WHEN** 用户查看回答区域
- **THEN** 界面明确显示证据不足状态，不伪造答案或推荐无来源结论

### Requirement: 展示问答生命周期状态

界面 SHALL 区分内核未启动、加载中、索引不可用、LLM 未配置、依赖失败、请求无效和普通
成功状态，并为可重试错误提供重试操作。错误展示 SHALL 使用 API 的中文 message，不能
展示 traceback 或内部异常类名。

#### Scenario: 内核不可用

- **GIVEN** 健康检查或问答请求无法连接 localhost API
- **WHEN** 用户打开或使用对话界面
- **THEN** 界面显示启动指引和重试操作，不显示空白页面或未处理异常

#### Scenario: LLM 配置错误

- **GIVEN** API 返回 `llm_not_configured` 或其他 503 稳定错误
- **WHEN** 用户查看失败结果
- **THEN** 界面显示中文配置指引，且不要求用户在浏览器中输入或保存 API key

### Requirement: 保持本地边界与可访问性

界面 SHALL 只调用配置的 localhost HTTP API，SHALL NOT 直接读取 vault、SQLite、LanceDB、
parquet 或图谱缓存，SHALL NOT 实现检索排序、提示词拼装和 citation 校验。主要操作 SHALL
支持键盘，答案、引用和错误文本在窄窗口中 SHALL 可读且不产生不可用溢出。

#### Scenario: 浏览器不绕过内核

- **GIVEN** 用户提交问题或展开引用
- **WHEN** 界面加载数据
- **THEN** 所有回答和引用均来自 API 响应，前端不自行读取或推导知识库内容
