# web-ui Specification（delta）

## MODIFIED Requirements

### Requirement: 提供模型供给设置表单

界面 SHALL 提供进入设置视图的入口与 LLM/embedding/rerank 三通道表单（base_url、
model、api_key、api_key_env、LLM 通道接口协议），经 `GET/PUT /api/settings` 读取
与保存；保存成功与失败 SHALL 给出中文反馈，校验错误 SHALL 就地展示。api_key 输入
SHALL 只写不回显（以占位状态表示已设置）；界面 SHALL NOT 把 key 写入 localStorage、
日志或任何可持久化的前端状态。表单 SHALL 提供厂商预设下拉（精选官方厂商与本地
端点，按「厂商 × 协议分支」组织），选中后 SHALL 填充该通道的 base_url/model/
api_key_env/protocol 与凭证模式且仍可手改；LLM 通道 SHALL 提供接口协议选择
（openai-chat / anthropic / openai-responses，缺省 openai-chat），embedding/rerank
通道 SHALL NOT 提供协议选择。界面 SHALL 说明自建网关反代与官方端点平级、手填即可
使用。LLM 通道回退生效时（响应 `llm_env_fallback` 非空）SHALL 展示说明提示。表单
SHALL 遵循既有可访问性要求：主要操作键盘可达，窄窗口可读。

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
- **THEN** 界面把该预设的 base_url/model/api_key_env/protocol 与凭证模式填入
  表单供用户修改确认，不自动提交保存；清除选择不改动已填字段

#### Scenario: 选择接口协议

- **GIVEN** 用户在 LLM 通道切换接口协议（如改为 anthropic）
- **WHEN** 保存设置
- **THEN** 提交值携带所选协议；embedding/rerank 通道界面不出现协议控件

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
