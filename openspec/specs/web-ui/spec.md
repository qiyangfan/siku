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

### Requirement: 未就绪时门控问答提交

界面 SHALL 在问答视图呈现模型供给就绪状态（来自 `GET /api/settings` 响应的
`ask_readiness`）：未就绪时 SHALL 置灰提交入口、以中文说明缺失的配置项，并提供
进入设置视图的引导入口；问题输入 SHALL 保持可用。就绪状态 SHALL 在问答视图可见
时刷新，设置保存成功后 SHALL 以保存响应中的最新状态刷新。就绪状态获取失败时
SHALL NOT 永久阻塞提交（保留既有提交后错误提示路径）。

#### Scenario: 未配置时置灰并引导

- **GIVEN** `ask_readiness.ready=false` 且 missing 含 `llm.api_key` 与
  `embedding.base_url`
- **WHEN** 用户打开问答视图
- **THEN** 提交按钮置灰不可点，界面以中文列出缺失项并展示「去设置」入口，
  问题输入仍可编辑

#### Scenario: 去设置并保存后恢复

- **GIVEN** 用户从未就绪的问答视图进入设置视图并保存了完整配置
- **WHEN** 用户回到问答视图
- **THEN** 提交入口恢复可用，引导卡片不再展示

#### Scenario: 就绪状态不可得时不锁死

- **GIVEN** `ask_readiness` 获取失败（内核离线之外的异常）
- **WHEN** 用户提交问题
- **THEN** 界面不置灰提交入口，提交后按既有错误路径展示 API 中文 message

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

界面 SHALL 提供资料库视图：来源清单（名称、摄取与索引状态徽标，含原件缺失与已
替代徽标，喂养条目展示上游路径）、导入入口、摄取进度反馈与全量重建入口（先经确认
对话框）。视图 SHALL 另提供来源目录管理区（添加、启停、移除与最后扫描时间展示）、
立即扫描入口（含全量校验选项）与确认式清理入口（展示待清理数量）。上述操作 SHALL
全部经 localhost API 完成并展示中文反馈；界面 SHALL NOT 直接读写 vault 文件内容，
SHALL NOT 直接读写来源目录。视图 SHALL 遵循既有可访问性要求：主要操作键盘可达，
来源区、清单与进度在窄窗口可读。

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

#### Scenario: 管理来源目录并触发扫描

- **GIVEN** 用户在来源目录区添加了一个本地目录
- **WHEN** 扫描执行
- **THEN** 界面展示扫描进度与中文结果反馈，清单出现新文档及其上游路径，来源区
  展示最后扫描时间

#### Scenario: 清理已标记文档

- **GIVEN** 清单存在原件缺失或已替代徽标的文档
- **WHEN** 用户点击清理
- **THEN** 界面先展示待清理数量并要求确认，仅确认后发起清理并展示结果反馈，
  取消时不产生任何请求

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

### Requirement: 图谱与 wiki 视图提供生成入口

图谱视图与 wiki 视图 SHALL 在只读阅读之外提供触发生成的界面入口：图谱未构建时
SHALL 展示「构建图谱」入口，已构建时 SHALL 提供「更新图谱」入口；wiki 未生成时
SHALL 展示「生成 wiki」入口，已生成时 SHALL 提供「重新生成 wiki」入口。全部入口
SHALL 经既有生成端点（`POST /api/graph`、`POST /api/wiki`）触发并沿用其默认幂等
路径；生成期间 SHALL 禁用入口并展示进行中文案；成功后 SHALL 刷新对应视图数据；
失败 SHALL 展示后端中文 message 并保留可重试入口。wiki 生成遇图谱产物缺失时
SHALL 就地提供「构建图谱」引导，构建成功后 SHALL 自动续跑生成。CLI 路径 SHALL
保持不变且与界面入口等价。

#### Scenario: 图谱空态构建

- **GIVEN** 图谱尚未构建（读取面返回 `graph_missing`）
- **WHEN** 用户点击「构建图谱」
- **THEN** 界面经 `POST /api/graph` 触发构建，展示进行中文案并禁用按钮，成功后
  自动加载统计与画布

#### Scenario: wiki 空态生成与图谱缺失引导

- **GIVEN** wiki 尚未生成且图谱产物缺失
- **WHEN** 用户点击「生成 wiki」
- **THEN** 界面展示需先构建图谱的中文说明与「构建图谱」入口；构建成功后自动
  续跑 wiki 生成并刷新条目清单

#### Scenario: 已建态更新与重新生成

- **GIVEN** 图谱与 wiki 均已生成
- **WHEN** 用户分别点击「更新图谱」与「重新生成 wiki」
- **THEN** 界面经既有生成端点触发（未变语料命中缓存，零 LLM 调用），完成后刷新
  统计、画布与条目清单，且旧选中条目不再与新清单同屏

#### Scenario: 生成失败反馈

- **GIVEN** LLM 通道未配置或生成中途失败
- **WHEN** 生成请求返回错误
- **THEN** 界面在视图内展示后端中文 message，按钮恢复可用，当前视图状态不丢失

### Requirement: 全局显示本地服务状态和浏览器恢复指引

React 主框架 SHALL 在所有视图显示用户可理解的本地服务连接状态。健康检查失败时 SHALL 在当前视图展示浏览器启动说明与“检查连接”操作；桌面应用的真实进程重启 SHALL 由 Tauri 恢复页提供。页面 SHALL NOT 将“内核已连接”等实现术语用作用户状态。

#### Scenario: 服务正常时显示连接状态

- **GIVEN** localhost API 健康检查成功
- **WHEN** 用户查看任意视图
- **THEN** 共享页头显示“服务正常”

#### Scenario: 服务不可用时跨视图提供可理解状态

- **GIVEN** localhost API 健康检查失败
- **WHEN** 用户查看问答、浏览、图谱、wiki、资料库或设置视图
- **THEN** 页头显示“服务未连接”，当前视图显示浏览器手动启动指引与只负责检查连接的按钮

### Requirement: 根据本地知识内容提供提问建议

问答页在本地服务可用时 SHALL 基于既有笔记与 wiki API 提供最多三条与当前知识库相关的提问建议。建议 SHALL 来自实际笔记标题/章节或 wiki 社区实体；不得使用假定固定项目内容的静态示例。导入的 Skill Markdown SHALL 与其他笔记一样参与推荐。生成建议 SHALL NOT 额外调用模型或直接访问本地文件和派生存储。

#### Scenario: 根据笔记和 wiki 展示建议

- **GIVEN** 笔记 API 返回标题或章节，或 wiki API 返回社区实体
- **WHEN** 用户打开问答页且本地服务可用
- **THEN** 界面展示最多三条由这些真实标题、章节或实体构成的提问建议

#### Scenario: 选择提问建议

- **GIVEN** 问答页显示一条提问建议
- **WHEN** 用户选择该建议
- **THEN** 界面将问题填入并聚焦输入框，不自动提交；用户可编辑后正常提交

#### Scenario: 空语料不显示固定样例

- **GIVEN** 笔记与 wiki 均为空
- **WHEN** 用户打开问答页
- **THEN** 界面提示导入资料或生成 wiki 后可获得建议，不显示虚构或固定项目示例

#### Scenario: 推荐读取失败不阻止手动提问

- **GIVEN** 一个或多个推荐来源暂时无法读取
- **WHEN** 用户打开问答页
- **THEN** 界面只展示成功读取的内容建议；没有任何来源可用时显示简短失败提示，问题输入与提交流程保持可用

#### Scenario: 已导入 Skill Markdown

- **GIVEN** Skill Markdown 已通过资料库导入并作为笔记返回
- **WHEN** 用户打开问答页
- **THEN** 建议可根据该笔记的标题或章节生成，界面不扫描未导入的本地 skill 文件
