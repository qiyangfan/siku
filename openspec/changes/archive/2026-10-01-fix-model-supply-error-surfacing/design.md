# 设计：模型供给错误分型与双面文案

## 决议

### 决议 #1：分型用子类，不用改现有捕获

`retrieve.errors` 新增两个子类，`graph.errors` 新增一个：

| 新类 | 基类 | 触发 | 结构化字段 |
|---|---|---|---|
| `ModelCredentialError` | `ModelNotAvailableError` | embedding/rerank 端点 401/403 | `channel: Literal["llm","embedding","rerank"]` |
| `ModelConfigFileError` | `ModelNotAvailableError` | 配置文件内容不可解析 / 段结构非法 | 无（`str(exc)` 已含路径与原因，只供日志） |
| `LlmAuthError` | `LlmProviderError` | LLM 端点 401/403 | 无 |

子类化而非改类名/换抛出点：全仓 `except ModelNotAvailableError`（serve 启动、
`_announce_supply_channels`、`_supply_search_service` 的 reranker=none 判定、
`embedding_rebuild_warnings`、`resolve_probe_target`、settings GET/PUT）与
`except LlmProviderError` 处理器一律不回退——基类照样捕获。代价是映射函数必须
把新类分支放在通用类分支**之前**（`isinstance` 首个命中即返回，顺序即优先级），
两处映射（`map_domain_error` / `map_ask_error` / `map_probe_error`）同一纪律，
并用测试锁死顺序。

`channel` 走 `args` 位置参（`super().__init__(message, channel)`），照
`ProtocolConfigError.kind`（ADR-0012）的先例保住 `copy`/`deepcopy`/`pickle` 圆厂；
文案层读结构化字段而不是解析英文 message 文本，避免脆耦合。

**否决备选**：
- *给基类加 `kind` 字段*（一处改动、无新类）：`ModelNotAvailableError` 的构造点
  分散在 provider、model_supply、settings 十余处，加必填字段要逐处改调用方；且
  「按类分文案」的既有下游写法会退化成「按类分 + 再 switch kind」两种风格并存。
- *401/403 直接改抛新独立类（不继承）*：会让 `except ModelNotAvailableError` 的
  reranker=none 判定与 settings 捕获全部漏接，属行为回退。
- *按 message 前缀匹配分型*：英文 message 是开发者面，随时可改；已被
  `ProtocolConfigError` 评审明确否决。

### 决议 #2：双面文案用显式 `surface` 参数，缺省 `"cli"`

`map_domain_error(exc, *, api_key_env, surface: Literal["cli","http"] = "cli")`。

- 缺省 `"cli"`：CLI 调用面（`retrieval_error_message`/`graph_error_message`/
  `ingest_error_message`）零改动、零漂移，既有 CLI 指引测试不失效。
- HTTP 调用点（`api/app.py` 各端点、`api/library.py` 任务错误、`map_read_error`、
  `map_ask_error` 末路回落、`map_probe_error` 末路回落）显式传 `"http"`。
- http 面硬约束：出现「设置」页指引 + 「保存后免重启生效」，MUST NOT 出现
  config.toml 路径与 `--embedding-base-url` 一类参数教程（用测试断言锁死，
  与既有 `/api/ask` 的 UI 导向测试同一口径）。
- CLI 面新分型文案要点：凭证被拒 → 核对 api_key/api_key_env 与 base_url 是否
  **成套**（不同厂商 key 不可跨端点用，这正是 401 的真实成因）；未配置 → 保持既有
  模板指引；坏文件 → 说明该文件当前不可解析、删除后重配不影响已摄取语料。

**否决备选**：
- *拆成 `map_cli_error` / `map_http_error` 两个函数*：其余 20 余个错误码文案两面
  完全相同，拆函数等于复制一份长表，将来漏改一侧是新缺陷。
- *给 `ErrorMapping` 加 `cli_message`/`http_message` 双字段*：调用方要选字段，
  选择点比参数多且更隐蔽；且 `ErrorMapping.message` 是既有内部契约，改名/加字段
  会牵动所有构造点。
- *靠调用方传入「是否在桌面」的运行时开关*：文案面是编译期事实（哪个函数在调），
  做成运行时状态只会漂移。

### 决议 #3：坏文件必须能自救——三个面同时打通

1. **PUT**：`load_config()` 抛 `ModelConfigFileError` 时，以空文件层
   （`ModelSupplyConfig()`）为基底继续 `apply_update` 并 `save_config` 原子替换；
   响应新增 `invalid_config_file_overwritten: bool`（缺省 False），True 即明示
   「原配置文件不可解析，已被本次保存覆盖」。只在**确证内容不可解析**时走这条路：
   `load_config` 的 `OSError`（读不到/无权限，内容未知）NOT 归入该类，仍按既有
   503 报错，绝不覆盖一个可能可读的文件——「不静默丢用户既有可用配置」的边界正在
   这里。
2. **GET**：同型错误经 http 面给可行动指引（设置页重新保存即可覆盖；或删除该配置
   文件后重配，删除只影响模型配置、不影响已摄取语料与索引）。
3. **serve 启动面**：`siku serve`（桌面 sidecar 的启动命令，
   `ui/src-tauri/src/main.rs` 传 `serve --with-ui`）今天因 `resolve_llm_channel`
   抛同型异常直接 `_fail` 退出——坏文件时应用根本起不来，PUT 自救路径无从可达。
   改为：捕获 `ModelConfigFileError` → stderr 明示告警（非静默）+ 英文日志 →
   以空文件层解析 LLM 通道继续启动；请求期各面现读，仍按 2/1 的指引报错或自救。

**否决备选**：
- *只修 PUT 不修 serve*：owner 基线描述的是「读就抛堵死保存」，但桌面链路里
  保存前先要服务活着；只修 PUT 的自救对桌面对象仍是死路（本条已复核代码确认，
  见报告）。
- *坏文件时自动备份为 `config.toml.bak` 再覆盖*：多出一个文件让手改用户更困惑，
  且 `save_config` 的原子替换语义（临时文件 + `os.replace`）已保证读者只会看到
  完整旧文件或完整新文件；旧内容既然不可解析，其信息量本就为「无」。
- *PUT 尽力抢救可解析的那几行*：TOML 局部解析需要自造容错解析器，且「猜用户想要
  什么」与 fail-loud 口径冲突；显式覆盖 + 明确告知是唯一的诚实路径。

### 决议 #4：readiness 与请求期同源，复用同一合并路径

`ask_readiness(config=None, *, cli: ModelSupplyConfig | None = None)`：CLI 层用与
文件层同形状的 `ModelSupplyConfig` 承载（三通道各一个 `ChannelValues`），内部把
`cli.llm` 传给 `resolve_llm_channel`、`cli.embedding` 传给 `_resolve_channel`，
其余判据不变。`masked_view(..., cli=...)` 由 `create_app` 用 serve 传入的
`llm_supply/embedding_supply/rerank_supply` 组装并透传。

判据（验收锁死）：`siku serve --embedding-base-url … --embedding-model …` 起来后
`GET /api/settings` 的 `ask_readiness.ready` 为 true 且 `missing` 为空。

不新写第二套合并：`_resolve_channel` 是请求期 `resolve_*_channel` 用的同一函数，
readiness 只是过去硬编码了 `cli=None`。同批把 `ask_readiness` docstring 的
「保证判定就绪而请求报未配置不可能发生」补回为真，并消除 `masked_view` 中
`llm_fallback`（含 CLI 层）与 `ask_readiness`（不含）的口径分裂。

**否决备选**：
- *给 readiness 加三个独立 kwargs（`llm_cli`/`embedding_cli`/`rerank_cli`）*：
  调用点要从 create_app 逐个透传，签名随通道数增长；`ModelSupplyConfig` 本就是
  「三通道 × 同形状」的既有载体。
- *readiness 改为直接调 `resolve_embedding_channel` 并捕异常*：会把「缺哪个字段」
  的信息丢掉（`missing` 是 `<channel>.<field>` 稳定 token 契约），只能给出
  「未配置」而给不出明细。

## 风险与边界

- 子类分支顺序错放＝新类被通用分支吞掉，文案回到误导态；用「401/403 的 http 文案
  不含『补全 base_url』字样」这类断言锁死，不靠代码审查。
- PUT 覆盖写会让用户失去坏文件里的原始内容（不可解析，实际信息量为零，但用户
  可能想手工修）；响应用显式字段告知，文案不承诺「可恢复」。
- readiness 计入 CLI 层后，`siku serve --embedding-base-url` 场景 UI 不再显示
  「去设置页配置」门控提示——这是修正（该部署确实可用），不是放松：文件层为空的
  判定分支与既有测试继续覆盖。
- 本批不动前端：`SettingsView` 在 GET 失败时早退（不渲染表单），坏文件场景下
  内核 PUT 已可用但表单不可达，登记为后续项（见 proposal Non-goals）。
