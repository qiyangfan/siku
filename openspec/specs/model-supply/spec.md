# model-supply Specification

## Purpose
统一管理 LLM、embedding、rerank 三类模型端点的供给配置：分层解析（CLI > 环境变量 >
配置文件 > 报错）、凭证保护、以及与桌面应用一致的本机配置文件位置。模型一律经
用户配置的端点（云或自部署）供给，内核不内置任何模型。

## Requirements

### Requirement: 分层解析模型供给配置

系统 SHALL 按 CLI 参数 > 环境变量 > 配置文件的优先级解析 LLM、embedding、rerank 三类
端点配置（`base_url`、`model`、凭证）；任一必需项在所有层级均缺失时，SHALL 返回
可行动的配置指引而非静默使用默认端点。配置文件路径 SHALL 使用平台应用配置目录下的
`config.toml`，与桌面数据根目录决策一致。

#### Scenario: 高层级覆盖低层级

- **GIVEN** config.toml 与 CLI 参数同时提供了 embedding 端点的 `model`
- **WHEN** 用户以 CLI 参数执行索引
- **THEN** 系统使用 CLI 参数值，config.toml 值仅在 CLI 未提供时生效

#### Scenario: 缺失必需配置时报错

- **GIVEN** 用户未以任何层级配置 embedding 端点
- **WHEN** 用户执行需要 embedding 的命令
- **THEN** 系统报错并给出 config.toml 模板位置或 CLI 参数示例，不回退到任何内置默认端点

#### Scenario: 配置文件三平台定位一致

- **GIVEN** 用户分别在 macOS、Windows、Linux 上安装
- **WHEN** 系统读取模型供给配置
- **THEN** 配置文件位于各自平台应用配置目录下的 `config.toml`，且解析行为在三平台一致

### Requirement: 保护模型凭证

系统 SHALL 支持两种凭证提供方式：配置文件内的 `api_key` 明文（文件创建时 SHALL 为
0600 权限）或 `api_key_env` 环境变量间接引用；系统 MUST NOT 将任何凭证写入日志、
索引元数据、评测基线、错误消息或 OpenAPI 契约。

#### Scenario: 明文 key 的文件权限

- **GIVEN** 用户在 config.toml 中直接写入 `api_key`
- **WHEN** 系统创建或重写该配置文件
- **THEN** 文件权限为 0600，非本用户不可读

#### Scenario: 凭证不泄漏

- **GIVEN** 一次使用明文 `api_key` 的端点调用因 401 失败
- **WHEN** 系统记录日志或返回错误
- **THEN** 日志、错误消息与任何持久化产物中均不包含该 key 的值
