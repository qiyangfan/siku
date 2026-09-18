# http-api Specification

## Purpose
把 Phase 1-3 的内核能力（摄取/检索/图谱/wiki）以 localhost HTTP API 暴露并冻结契约，
作为 UI ↔ 内核边界的内核侧落地（ADR-0002 红线），使后续 UI 与内核可并行演进。

## Requirements

### Requirement: 提供 localhost HTTP 内核端点

系统 SHALL 提供 `siku serve` 启动仅绑定 127.0.0.1 的 FastAPI 应用，暴露健康检查与
摄取/检索/图谱/wiki 端点；端点 SHALL 复用既有服务层且 SHALL NOT 包含业务逻辑；
响应字段 SHALL 与 CLI `--json` 输出同构。

#### Scenario: 健康检查

- **GIVEN** 服务已启动
- **WHEN** 客户端请求 `GET /api/health`
- **THEN** 返回 200 与 `{status: "ok", version: <当前版本>}`

#### Scenario: 摄取返回来源级报告

- **GIVEN** 一个存在的本地文档路径
- **WHEN** 客户端请求 `POST /api/ingest` `{source: <路径>}`
- **THEN** 返回 200 与来源级四计数报告（created/updated/skipped/ignored），语义与 `siku ingest` 一致

#### Scenario: 检索返回带来源锚点的结果

- **GIVEN** 已建立检索索引
- **WHEN** 客户端请求 `POST /api/search` `{query: <自然语言>}`
- **THEN** 返回 200 与结果列表，每条携带 chunk 锚点与各段分数，字段与 `siku search --json` 同构

#### Scenario: 图谱构建返回体检报告

- **GIVEN** 一个已摄取的 vault
- **WHEN** 客户端请求 `POST /api/graph` `{vault, data_dir}`
- **THEN** 返回 200 与体检报告（节点/边/社区/同名实体/缓存命中/LLM 调用/告警），字段与 `siku graph --json` 同构

#### Scenario: wiki 生成返回条目统计

- **GIVEN** 图谱与摘要缓存已就绪
- **WHEN** 客户端请求 `POST /api/wiki` `{data_dir}`
- **THEN** 返回 200 与 `{entries, cache_hits, llm_calls, empty_graph}`

### Requirement: 领域错误归一为 HTTP 状态与稳定错误码

API 层 SHALL 把领域错误体系映射为稳定的三类状态码（状态前置 409 / 输入不可处理 422 /
外部依赖不可用 503）与稳定英文错误码、简体中文文案；SHALL NOT 泄漏堆栈或裸异常信息；
错误文案 SHALL 与 CLI 共享同一映射来源。

#### Scenario: 无裸异常穿透

- **GIVEN** 任一领域错误被端点触发（如缺索引、缺 LLM key、限流）
- **WHEN** API 返回错误响应
- **THEN** 响应为 `{code, message}` 结构，message 为简体中文指引，响应中无堆栈与英文异常类名

#### Scenario: 状态前置类错误返回 409

- **GIVEN** 未建立检索索引
- **WHEN** 客户端请求 `POST /api/search`
- **THEN** 返回 409 与 `code=index_unavailable`，message 提示先执行索引

#### Scenario: 依赖不可用类错误返回 503

- **GIVEN** 未配置 LLM API key
- **WHEN** 客户端请求 `POST /api/graph` 且语料需要真实抽取
- **THEN** 返回 503 与 `code=llm_not_configured`，message 给出中文配置指引

### Requirement: OpenAPI 契约快照冻结入库

系统 SHALL 把 OpenAPI 契约快照冻结到 `contracts/openapi.json`；契约漂移 SHALL 使
测试失败并要求显式刷新；快照 SHALL 注明生成方式。

#### Scenario: 契约漂移即失败

- **GIVEN** 契约快照已入库
- **WHEN** 端点模型或结构被修改而未刷新快照
- **THEN** 契约测试失败并提示刷新命令

#### Scenario: 显式刷新快照

- **GIVEN** 契约变更经评审确认
- **WHEN** 开发者执行刷新命令
- **THEN** 快照更新且测试恢复通过，diff 进入提交评审

### Requirement: LLM 端点可配置且默认行为不变

`graph`/`wiki` SHALL 支持经参数指定 openai 兼容端点的 base_url 与模型名，使任意
兼容网关（如 muniu、ollama）即插即用；未指定时 SHALL 保持现有默认（DeepSeek）与
全部既有行为（含缺 key 指引、缓存语义）不变。

#### Scenario: 指向自建网关

- **GIVEN** 用户运行 muniu 网关并签发访问 key
- **WHEN** 用户以 `--llm-base-url http://127.0.0.1:8787/v1 --llm-model <别名>
  --api-key-env <变量>` 执行 `siku graph`
- **THEN** 抽取与摘要请求全部经网关完成，图谱产物与直连同构

#### Scenario: 默认行为不变

- **GIVEN** 用户未传任何 LLM 端点参数
- **WHEN** 执行 `siku graph` / `siku wiki`
- **THEN** 行为与既有 DeepSeek 默认完全一致（含缓存键语义，不产生跨端点缓存污染）

#### Scenario: 网关文档明示语义缓存约束

- **GIVEN** 用户经 muniu 网关使用 siku
- **WHEN** 查阅部署文档
- **THEN** 文档明示 siku 租户必须关闭网关语义缓存（模糊命中破坏幂等闸门）与
  换通道需同步摘要身份的注意事项
