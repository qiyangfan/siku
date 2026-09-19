# 提案：桌面 UI 设置中心（BYOK 三通道端点配置表单）

## Why

BYOK 端点化落地后，桌面用户上手的第一阻断点是模型供给配置：当前唯一途径是手工编辑
平台配置目录下的 `config.toml`（0600），字段、格式与权限对新手都是门槛，且改完需重启
serve 才生效。设置中心补上「装上 → 配模型 → 问」链路的中间一环：表单化三通道
（LLM/embedding/rerank）的 base_url/model/key 配置，经 localhost API 写回同一
config.toml，保存后免重启生效。这是 HANDOFF「下一阶段候选」第 1 项（2026-09-19
用户对齐确认）。

## What Changes

- 新增设置读写 API（additive，OpenAPI 快照显式刷新）：
  - `GET /api/settings`：三通道掩码视图（base_url/model/api_key_env/key 是否已设），
    标注由环境变量层提供的字段；任何响应不回显 key 明文。
  - `PUT /api/settings`：校验（复用 `ChannelValues` 形状）后合并写入 config.toml
    （0600 保持、原子替换），返回写入后掩码视图与告警（如 embedding 模型身份变更 →
    需全量重建索引的中文指引）。
  - `POST /api/settings/test`：按单通道对用户端点发起最小连通性探测，复用既有
    provider 错误映射返回稳定错误码与中文指引；不做任何持久化。
- serve 的 provider 缓存失效机制：设置写入后缓存的三通道 provider 失效，下一次请求
  按新配置重建（连接池随之重建），无需重启。
- config 写入路径收敛到 `model_supply.save_config`：补原子写入（临时文件 + rename）
  与 0600 权限保持的回归测试。
- UI 新增设置视图：三通道表单（base_url/model/api_key/api_key_env），key 只写不回显
  （已设置用占位标识），保存与连通性测试按钮，中文文案与既有错误展示风格一致；
  浏览器开发模式与 Tauri 同源模式均经相对 `/api` 调用。

## 受影响决策

- 红线 2 / ADR-0002：UI 只经 localhost HTTP API 访问内核——本 change 是该边界的
  落实：表单不直写配置文件，全部经新增端点。
- ADR-0009：config.toml 分层解析（CLI > 环境变量 > 文件）与凭证保护语义不变；设置
  中心写入的是同一文件、同一形状，环境变量层继续优先于文件层。
- 不新增 ADR：无架构级新决策；provider 缓存失效属 serve 内部实现语义，随 change
  评审记录。

## 与项目路线的关系

HANDOFF 下一阶段候选第 1 项（2026-09-19 对齐）。属 Phase 5 之后的桌面上手补齐：
不改变发布形态，为「桌面资料管理」（候选第 2 项）铺路，两者合成完整无 CLI 上手体验。

## Non-goals

- 不做桌面资料导入/摄取/索引管理 UI（另行立项，见 `add-desktop-library`）。
- 不做 embedding 变更后的自动重建索引：只返回需重建的中文指引，重建仍走既有 CLI
  管线（换 embedding 模型必须全量重建是既有约束）。
- 不改变既有 `/api/ask`、`/api/health` 等端点契约与问答语义；OpenAPI 变更仅限新增
  端点并显式刷新快照。
- 不做账号、多配置档案、配置导入导出、云同步、遥测。
- 不做远程访问与鉴权：serve 仍仅绑定 loopback，设置端点不引入认证体系。
- 不新增 settings 类 CLI 命令：CLI 用户直接编辑 config.toml，既有文档已覆盖。
- 不改 CLI 既有参数与环境变量语义。

## 边界裁决

- 设置读写只作用于 config.toml 文件层：环境变量层不由 UI 管理（env 优先于文件的
  既有语义保持；UI 对被 env 覆盖的字段给出提示而非禁止保存）。
- key 的唯一落点仍是 0600 的 config.toml 或 `api_key_env` 间接引用：设置 API 的
  请求与响应不落日志、不进 OpenAPI 契约明文示例、不回显。
- 连通性测试是对用户自配端点的瞬时调用（红线 1 允许的 BYOK 形态），不携带任何语料
  内容，仅用最小探测负载；不回显上游错误体（沿 BYOK 评审 P2 的收紧方向）。
- rerank 通道保持可选一等语义：表单留空 = rerank none（RRF-only），不强制配置。
