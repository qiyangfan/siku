# 提案：模型供给错误分型与双面文案（凭证被拒 / 坏配置文件 / CLI 层就绪 / HTTP 面话术）

## Why

HANDOFF「已知边界与下一步」登记的 4 条上报待立项缺陷（第十六批评审确认，见归档件
`2026-09-26-refine-model-config-and-library-ux` review.md），共同构成桌面用户
（发布阶段二的主面，ADR-0002）在「配模型」这一步上的三条死路：

1. **凭证被拒被说成未配置**：`retrieve/api_providers.py` 的 `_endpoint_error` 把
   401/403 映射为 `ModelNotAvailableError`（message 写着 `rejected the credentials`），
   而该类同时承载「未配置 / 凭证被拒 / 端点不可用」三种语义，下游按类出文案，
   于是拿着正确端点、错误 key 的用户被告知「去补全 base_url 与 model」——按这条
   指引改配置不会解决问题。LLM 侧同型：`graph/providers.py` 的 `_interpret` 只对
   429 与超长分型，401/403 落进通用 `LlmProviderError`。
2. **config.toml 损坏是死路**：`load_config` 对坏文件抛 `ModelNotAvailableError`，
   而 `PUT /api/settings` 走 `apply_update(load_config(), update)`——文件一坏读就抛，
   桌面用户想用「设置页重新保存」覆盖坏文件这条路被彻底堵死；更前置的是
   `siku serve`（桌面 sidecar 的启动命令）在解析 LLM 通道时同一异常直接退出，
   应用根本起不来，设置页无从打开。
3. **CLI 传参时假未就绪**：`ask_readiness` 只吃文件层 + 环境变量层，不吃 serve 的
   CLI 层（`--embedding-base-url` 等），而同一函数的 docstring 与 `masked_view` 的
   `llm_fallback` 注释都声称「与请求期同源、含 serve 的 CLI 层」——就绪判定是落后
   的一侧，真实可用的部署被 UI 门控判为未配置。
4. **HTTP 面文案是 CLI 导向**：`messages.map_domain_error` 教用户编辑 config.toml
   路径与 `--embedding-base-url` 等命令行参数，CLI 与 `api/*.py` 共用同一函数；
   桌面用户没有 CLI 语境，指引不可执行（ADR-0002 发布阶段二、ADR-0009「报错必须
   可行动」）。

## What Changes

- **错误分型（新增子类，不改既有捕获）**：`retrieve.errors` 增
  `ModelCredentialError(ModelNotAvailableError)`（携带结构化 `channel`：
  llm/embedding/rerank）与 `ModelConfigFileError(ModelNotAvailableError)`；
  `graph.errors` 增 `LlmAuthError(LlmProviderError)`。401/403 与坏配置文件分别
  落到新类，`load_config` 中「读不到文件」（OSError）与「内容不可解析」不再同类。
- **双面文案**：`map_domain_error` 增 `surface: Literal["cli", "http"]`（缺省
  `"cli"` 保持 CLI 现状），HTTP 各调用点显式传 `"http"`：一律指向「设置」页并说明
  保存后免重启生效，MUST NOT 出现 config.toml 路径或命令行参数教程。CLI 面新分型
  文案区分「凭证被拒（api_key/api_key_env 与 base_url 须成套，不同厂商 key 不可跨
  端点）」与「未配置」。
- **坏文件自救**：`PUT /api/settings` 在 `load_config()` 抛 `ModelConfigFileError`
  时以空文件层为基底继续合并写入并原子替换坏文件，响应新增布尔字段明示
  「原配置文件不可解析，已被本次保存覆盖」；`GET /api/settings` 同型错误给可行动
  指引；`siku serve` 遇同型错误明示告警后以空文件层启动（不再退出）。
- **就绪与请求期同源**：`ask_readiness` 接受与请求期相同的 CLI 层输入（复用既有
  `_resolve_channel`/`resolve_*_channel` 路径，不造第二套合并），`masked_view`
  透传 serve 的三通道 CLI 层。

## 受影响决策

- **ADR-0009（BYOK 端点化）**：本 ADR 的代价条款写明「无端点即无向量检索：报错
  必须可行动」。四条缺陷都是「报错可行动」这一承诺的欠账——分型错位、指向不可用
  的路径、判定落后于配置，均在 ADR-0009 语义范围内修复，不改动分层优先级与凭证
  保护口径。
- **ADR-0012（多协议 LLM 接入）**：LLM 侧 401/403 分型发生在 `_interpret`，与协议
  分支无关（三协议同一状态码语义）；协议越界错误的结构化 `kind` 分型
  （`ProtocolConfigError`）是本批 `channel` 结构化字段的先例与形状参照。
- **ADR-0002（三阶段发布）**：桌面（阶段二）用户面无 CLI 语境，是双面文案的直接
  依据；sidecar 以 `siku serve` 启动，故坏文件的自救必须包含启动面。
- **红线 1（UI↔内核只经 localhost API）**：分型与话术全部住内核，前端只消费
  `{code, message}` 与新布尔字段，无业务逻辑下沉。

## 与项目路线的关系

Phase 5++「桌面上手补齐」的收尾打磨：HANDOFF 明示这 4 条为「上报待立项」，
owner 2026-09-30 点名为一批立项。不涉及新增长端点与能力域。

## Non-goals

- **不改错误码枚举**：`model_not_available` / `llm_provider_error` 等对外稳定 code
  保持不变，分型只体现在文案与结构化字段——改 code 会让既有客户端与 UI 的
  `code` 分支失配，且本批不许动前端。
- **不新增前端逻辑**：UI 仍按内核 `message`/`ask_readiness` 渲染。已发现
  `SettingsView` 在 GET 失败时早退、不渲染表单（坏文件时内核 PUT 已可用但表单
  不可达），属前端后续项，本批只在内核解除「PUT 被读堵死」，登记不修。
- **不做端点可达性判定与自动重试**：就绪判定不含连通性（归探测端点），凭证被拒
  不做自动换 key 或跨端点试探。
- **不改分层优先级与凭证保护口径**（ADR-0009）：CLI > env > 文件、SecretStr 掩码、
  0600 均不动。
- **不做坏配置文件的自动修复/备份回滚**：只允许「用户显式保存即覆盖」，不静默
  改写、不生成 .bak（多出一份文件反而让手改用户困惑）。
- **不引入新依赖**。
