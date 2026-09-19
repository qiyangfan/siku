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

### Requirement: 提供模型供给设置表单

界面 SHALL 提供进入设置视图的入口与 LLM/embedding/rerank 三通道表单（base_url、
model、api_key、api_key_env），经 `GET/PUT /api/settings` 读取与保存；保存成功与
失败 SHALL 给出中文反馈，校验错误 SHALL 就地展示。api_key 输入 SHALL 只写不回显
（以占位状态表示已设置）；界面 SHALL NOT 把 key 写入 localStorage、日志或任何可
持久化的前端状态。表单 SHALL 遵循既有可访问性要求：主要操作键盘可达，窄窗口可读。

#### Scenario: 编辑并保存通道配置

- **GIVEN** 用户在设置表单填写 LLM 通道的 base_url/model/key
- **WHEN** 用户提交保存
- **THEN** 界面经 `PUT /api/settings` 保存并展示中文成功反馈；失败时展示 API 中文
  message 并保留已输入内容

#### Scenario: key 只写不回显

- **GIVEN** config.toml 已设置某通道 api_key
- **WHEN** 用户打开设置表单
- **THEN** 该通道 key 输入框为空并以「已设置」占位标识，界面任何位置不显示 key 明文

#### Scenario: embedding 变更告警呈现

- **GIVEN** PUT 响应包含需全量重建索引的告警
- **WHEN** 界面收到保存结果
- **THEN** 界面显著展示该中文告警与重建指引，不误导为保存失败

#### Scenario: 连通性测试反馈

- **GIVEN** 用户在任一通道点击连通性测试
- **WHEN** `POST /api/settings/test` 返回成功或失败
- **THEN** 界面分别展示成功耗时或中文失败指引，测试期间阻止重复点击

### Requirement: 提供桌面资料库视图

界面 SHALL 提供资料库视图：来源清单（名称、摄取与索引状态徽标）、导入入口、摄取
进度反馈与全量重建入口（先经确认对话框）。导入与进度 SHALL 全部经 localhost API
完成并展示中文反馈；界面 SHALL NOT 直接读写 vault 文件内容。视图 SHALL 遵循既有
可访问性要求：主要操作键盘可达，清单与进度在窄窗口可读。

#### Scenario: 导入并跟踪进度

- **GIVEN** 用户在资料库视图选择本地文件导入
- **WHEN** 摄取任务执行
- **THEN** 界面展示进度与逐文件结果（成功/失败中文说明），结束后刷新清单状态

#### Scenario: 空状态引导

- **GIVEN** 桌面 vault 为空
- **WHEN** 用户打开资料库视图
- **THEN** 界面展示导入引导与支持格式说明，不展示空白列表

#### Scenario: 重建确认

- **GIVEN** 用户点击全量重建索引
- **WHEN** 确认对话框被确认或取消
- **THEN** 仅确认后发起重建并展示进度反馈，取消时不产生任何请求

### Requirement: 提供浏览/图谱/wiki 三个只读视图

界面 SHALL 提供视图导航与三个只读视图：浏览（分页清单 + Markdown 只读渲染）、
图谱（Sigma.js WebGL 画布：节点搜索、邻域展开、社区着色、截断提示）、wiki（条目
清单 + 阅读 + 「可重建」时效提示）。全部数据 SHALL 经只读端点获取；Markdown 渲染
SHALL 产出安全只读输出（不执行内嵌脚本）；图谱画布 SHALL 遵守服务端截断边界。
视图 SHALL 遵循既有可访问性要求：主要操作键盘可达，窄窗口可读。

#### Scenario: 浏览阅读

- **GIVEN** 用户在浏览视图选中一篇笔记
- **WHEN** 内容加载
- **THEN** 界面渲染只读 Markdown 与来源锚点信息，不提供编辑入口

#### Scenario: 图谱邻域展开

- **GIVEN** 图谱视图已展示聚合画布
- **WHEN** 用户搜索并点击一个实体展开邻域
- **THEN** 画布增量展开该实体的有界邻域，超限时展示截断提示

#### Scenario: wiki 阅读与时效提示

- **GIVEN** wiki 存在已生成的条目
- **WHEN** 用户打开 wiki 视图并阅读一条
- **THEN** 界面展示条目内容与生成时间，提示可重建但不自动触发

#### Scenario: 实体联动问答

- **GIVEN** 用户在图谱视图选中一个实体
- **WHEN** 用户选择「在问答中查询」
- **THEN** 界面切换到问答视图并预填该实体相关的问题，不自动发送
