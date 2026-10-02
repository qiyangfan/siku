# web-ui Specification（delta）

## MODIFIED Requirements

### Requirement: 提供模型供给设置表单

界面 SHALL 提供进入设置视图的入口与 LLM/embedding/rerank 三通道表单（base_url、
model、api_key、api_key_env），经 `GET/PUT /api/settings` 读取与保存；保存成功与
失败 SHALL 给出中文反馈，校验错误 SHALL 就地展示。api_key 输入 SHALL 只写不回显
（以占位状态表示已设置）；界面 SHALL NOT 把 key 写入 localStorage、日志或任何可
持久化的前端状态。表单 SHALL 提供厂商预设下拉（精选官方厂商与本地端点），选中后
SHALL 填充该通道的 base_url/model/api_key_env 与凭证模式且仍可手改；LLM 通道回退
生效时（响应 `llm_env_fallback` 非空）SHALL 展示说明提示。表单 SHALL 遵循既有可
访问性要求：主要操作键盘可达，窄窗口可读。

#### Scenario: 编辑并保存通道配置

- **GIVEN** 用户在设置表单填写 LLM 通道的 base_url/model/key
- **WHEN** 用户提交保存
- **THEN** 界面经 `PUT /api/settings` 保存并展示中文成功反馈；失败时展示 API 中文
  message 并保留已输入内容

#### Scenario: key 只写不回显

- **GIVEN** config.toml 已设置某通道 api_key
- **WHEN** 用户打开设置表单
- **THEN** 该通道 key 输入框为空并以「已设置」占位标识，界面任何位置不显示 key 明文

#### Scenario: 选择厂商预设自动填充

- **GIVEN** 用户在某通道展开厂商预设下拉并选择一个厂商
- **WHEN** 预设被选中
- **THEN** 界面把该预设的 base_url/model/api_key_env 与凭证模式填入表单供用户
  修改确认，不自动提交保存；清除选择不改动已填字段

#### Scenario: LLM 回退生效提示

- **GIVEN** 设置响应 `llm_env_fallback` 非空（环境变量回退生效）
- **WHEN** 用户查看 LLM 通道表单
- **THEN** 界面说明当前实际生效的回退端点与来源环境变量名，不误导为「完全未配置」

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
对话框）。导入入口 SHALL 呈现为文件选择控件形态：点击可打开系统文件选择器，且
支持把文件拖入投放；视图 SHALL 另提供来源目录管理区（添加、启停、移除与最后扫描
时间展示）、立即扫描入口（含全量校验选项）与确认式清理入口（展示待清理数量）。
物理删除类清理入口 SHALL 以危险配色标识并与普通操作区分。上述操作 SHALL 全部经
localhost API 完成并展示中文反馈；界面 SHALL NOT 直接读写 vault 文件内容，
SHALL NOT 直接读写来源目录。视图 SHALL 遵循既有可访问性要求：主要操作键盘可达，
来源区、清单与进度在窄窗口可读。

#### Scenario: 导入并跟踪进度

- **GIVEN** 用户在资料库视图选择本地文件导入
- **WHEN** 摄取任务执行
- **THEN** 界面展示进度与逐文件结果（成功/失败中文说明），结束后刷新清单状态

#### Scenario: 拖拽文件投放

- **GIVEN** 用户把若干本地文档拖到导入区上方
- **WHEN** 松开投放
- **THEN** 界面以与点击选择相同的路径发起摄取；拖拽悬停时投放区有可见高亮反馈

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

### Requirement: 图谱与 wiki 视图提供生成入口

图谱视图与 wiki 视图 SHALL 在只读阅读之外提供触发生成的界面入口：图谱未构建时
SHALL 展示「构建图谱」入口，已构建时 SHALL 提供「更新图谱」入口；wiki 未生成时
SHALL 展示「生成 wiki」入口，已生成时 SHALL 提供「重新生成 wiki」入口。全部入口
SHALL 经既有生成端点（`POST /api/graph`、`POST /api/wiki`）触发并沿用其默认幂等
路径；生成期间 SHALL 禁用入口并展示进行中文案；成功后 SHALL 刷新对应视图数据；
失败 SHALL 展示后端中文 message 并保留可重试入口。wiki 生成遇图谱产物缺失时
SHALL 就地提供「构建图谱」引导，构建成功后 SHALL 自动续跑生成。CLI 路径 SHALL
保持不变且与界面入口等价。空态 SHALL 展示模型通道就绪提示：LLM 凭证缺失时说明
缺项并提供进入设置的入口，就绪时说明可直接构建；提示 SHALL NOT 置灰或拦截生成
入口，就绪状态不可得时 SHALL 静默省略提示。

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

#### Scenario: 空态就绪提示不拦截生成

- **GIVEN** LLM 通道凭证缺失且图谱处于未构建空态
- **WHEN** 用户查看空态卡片
- **THEN** 界面展示缺项说明与「去设置」入口，「构建图谱」按钮保持可用，点击后
  仍按既有请求期错误映射反馈

#### Scenario: 已建态更新与重新生成

- **GIVEN** 图谱与 wiki 均已生成
- **WHEN** 用户分别点击「更新图谱」与「重新生成 wiki」
- **THEN** 界面经既有生成端点触发（未变语料命中缓存，零 LLM 调用），完成后刷新
  统计、画布与条目清单，且旧选中条目不再与新清单同屏

#### Scenario: 生成失败反馈

- **GIVEN** LLM 通道未配置或生成中途失败
- **WHEN** 生成请求返回错误
- **THEN** 界面在视图内展示后端中文 message，按钮恢复可用，当前视图状态不丢失
