# HTTP API Specification Delta

## ADDED Requirements

### Requirement: 提供带来源引用的单轮问答端点

系统 SHALL 提供 `POST /api/ask` 单轮问答端点。端点 SHALL 复用既有混合检索获取有界上下文，
再调用用户配置的 LLM 生成回答；正常响应 SHALL 返回答案、`request_id`、模型身份和完整
来源引用。问题、`top_k`、`candidate_k` 和打包后的上下文 SHALL 受服务端硬上限约束，超限
不得静默截断证据。端点 SHALL NOT 接受或持久化账号凭证、会话历史或除本次 LLM 瞬时调用
之外的远程状态。

#### Scenario: 基于检索上下文返回回答

- **GIVEN** 检索索引可用，且问题能召回至少一个上下文片段
- **WHEN** 客户端请求 `POST /api/ask` `{question, top_k?, candidate_k?}`
- **THEN** 返回 200，包含非空 `answer`、`request_id`、`model`、检索摘要和至少一条引用；每条
  引用包含本次检索结果的 `citation_id`、source name、note path、anchor、chunk id 与 hash，
  且所有 citation id 均属于本次上下文

#### Scenario: 证据不足时拒答

- **GIVEN** 问题合法但检索没有命中可用上下文
- **WHEN** 客户端请求问答端点
- **THEN** 返回 200，`insufficient_evidence=true`、答案为确定性中文指引、引用为空、
  `model` 为当前配置的模型身份，且不调用 LLM

#### Scenario: 拒绝未授权引用

- **GIVEN** LLM 返回未知 citation id、非 JSON 或字段不完整的回答
- **WHEN** 服务端校验 LLM 输出
- **THEN** 返回 503 与 `code=llm_provider_error`，不返回未经校验的答案或 traceback；不得
  误用图谱抽取的 422 错误，message 使用问答适用的中文文案

### Requirement: 问答请求保持无状态并可追踪

每次问答 SHALL 生成唯一 `request_id` 并写入问答链路日志；成功和确定性无证据响应 SHALL
返回该 id，错误响应继续复用现有 `{code, message}` 结构。服务端 SHALL NOT 保存会话历史。
相同请求不要求服务端复用答案缓存，LLM key SHALL 只从服务进程配置读取。

#### Scenario: 页面刷新不恢复服务端会话

- **GIVEN** 一次问答已经完成
- **WHEN** 客户端重新请求健康检查或发起新问题
- **THEN** 新请求拥有独立 `request_id`，服务端不读取上一轮对话内容

### Requirement: 问答错误复用稳定 HTTP 语义

问答端点 SHALL 复用现有稳定 HTTP 状态/错误码体系：请求无效返回 422，索引或前置状态不
满足返回 409，LLM key 缺失、限流、断连、超长、空返回和结构化输出失败返回 503；错误响应
SHALL 为 `{code, message}` 且不包含英文异常类名或堆栈。问答错误文案可以按问答场景提供，
但不得改变既有 graph/wiki 端点的错误语义。

#### Scenario: LLM 未配置

- **GIVEN** 检索命中上下文但服务进程没有用户自配 LLM key
- **WHEN** 客户端请求问答
- **THEN** 返回 503 与 `code=llm_not_configured`，message 给出中文配置指引
