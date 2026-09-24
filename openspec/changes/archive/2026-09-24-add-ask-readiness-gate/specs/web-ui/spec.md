# web-ui Specification（delta）

## ADDED Requirements

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
