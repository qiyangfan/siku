# 任务清单

## 约束冻结（实现前）

- [x] 冻结分型形状：三个新子类 + 子类化不改既有捕获；映射分支新类置于通用类之前
      （design.md 决议 #1）。
- [x] 冻结双面文案口径：`surface` 显式参数、缺省 `"cli"`、http 面禁现
      config.toml 路径与 CLI 参数教程（决议 #2）。
- [x] 冻结坏文件自救三面：PUT 空层基底 + 响应告知字段、GET 指引、serve 明示告警后
      以空文件层启动；OSError 不算不可解析（决议 #3）。
- [x] 冻结 readiness 同源签名与判据：`ask_readiness(config, *, cli)`，
      CLI 层用 `ModelSupplyConfig` 承载，复用 `_resolve_channel`（决议 #4）。

## 测试先行（先红）

- [x] `tests/test_retrieve_api_providers.py`：401/403 → `ModelCredentialError`
      且 `channel` 为 embedding/rerank；`ModelConfigFileError` 与通用类分型可捕获
      （基类照样接住）。
- [x] `tests/test_graph_provider.py`：401/403 → `LlmAuthError`（三协议一致），
      429/超长/断连剧本不回退。
- [x] `tests/test_model_supply.py`：坏 TOML 与非法段 → `ModelConfigFileError`；
      读权限失败不属该类；`ask_readiness(cli=…)` 计入 CLI 层。
- [x] `tests/test_api_settings.py`：坏文件下 PUT 仍覆盖写入并携带告知字段、GET 指引
      可行动且无 CLI 教程；serve CLI 层下 `ask_readiness.ready=true`。
- [x] `tests/test_api.py` / `tests/test_model_supply_api.py`：http 面文案不含
      config.toml 路径与 `--embedding-base-url`；凭证被拒分型文案区分「成套」；
      CLI 面既有指引零漂移。
- [x] `tests/test_cli.py`：坏文件下 `siku serve` 不退出且 stderr 明示告警。

## 内核（src/siku）

- [x] `retrieve/errors.py`：`ModelCredentialError`（`channel` 进 args）、
      `ModelConfigFileError`。
- [x] `retrieve/api_providers.py`：`_endpoint_error` 401/403 抛
      `ModelCredentialError`，channel 用小写稳定 token。
- [x] `graph/errors.py` + `graph/providers.py`：`LlmAuthError`，`_interpret`
      401/403 分型（先于超长/通用分支）。
- [x] `model_supply.py`：`load_config` 坏内容 → `ModelConfigFileError`（OSError
      仍走通用类）；`ask_readiness` 增 `cli` 层并复用 `_resolve_channel`；
      docstring 口径修订。
- [x] `api/messages.py`：`surface` 参数 + 三个新类分支（cli/http 两套文案），
      `map_ask_error`/`map_read_error` 以 http 面回落。
- [x] `api/settings.py`：`masked_view` 透传 CLI 层；`map_probe_error` 凭证被拒与
      坏文件分支前置。
- [x] `api/models.py` + `api/app.py`：`SettingsWriteResponse.invalid_config_file_overwritten`；
      PUT 空层自救；GET/PUT/其余端点显式 `surface="http"`；`api/library.py` 同。
- [x] `cli.py`：serve 启动面对 `ModelConfigFileError` 明示告警 + 空文件层继续；
      `_llm_config_error_message` 增坏文件中文文案。
- [x] `contracts/openapi.json` 再生成（防漂移测试兜底）。

## 交付门禁

- [x] `uv run ruff check .` / `uv run ruff format --check .` 全绿。
- [x] `uv run pytest` 全绿（零失败零跳过）。
- [x] `openspec validate --specs --strict` 与 `--changes --strict` 通过。
- [x] 前端随行（超出「零改动」原计划，收口由 owner 侧完成）：`ui/src/api.ts` 的 `SettingsWriteResponse` 补 `invalid_config_file_overwritten`；`SettingsView` 用独立 `color="yellow" role="status"` 告警呈现「原配置文件不可解析」自救告知——**不复用 `warnings` 区块**，其标题固定为「需要重建索引」，把覆盖写塞进去会误导成索引问题；用例断言告知出现、且下一次正常保存后撤下（不滞留成常驻文案）。门禁：vitest 107/107、`tsc -b --noEmit`、`eslint .`、`vite build` 全绿。
      登记为后续项。

## 评审迭代循环补修（2026-10-01，R1→R2）

- [x] **第三种成因独立成类**：`retrieve/errors.py` 新增 `ModelConfigFileUnreadableError`
      （权限/IO 读不到，内容未知）。原实现把它抛成基类 `ModelNotAvailableError`，与「通道未配置」
      共用文案——用户被告知去补全其实配好了的 base_url/model，正是本变更要消灭的顶替；
      仍挂基类子类位置，`except ModelNotAvailableError` 处理器零回退。
- [x] `api/messages.py`：给该类独立的 cli/http 两套文案（明说「无法读取、非内容损坏、不会由保存覆盖」）；
      `PUT` 的覆盖分支只捕 `ModelConfigFileError`，故读不到时仍不覆盖（spec 判据）。
- [x] `api/settings.py`：`map_probe_error` 补该类的独立分支——R2 自查发现这里漏捕，权限故障会落回
      「端点配置不完整：请检查该通道的 base_url、model 与 api_key」，正是 spec 禁止的顶替。
- [x] `cli.py`：启动横幅不再把「不可解析」的配置文件故障播报成「未配置 / none（RRF-only）」——serve
      容忍坏文件继续启动后，embedding/rerank 解析会再读同一个坏文件，原实现两条输出自相矛盾。
      R2 收敛：`unreadable` 分支删除（serve 在 LLM 解析处即快速失败退出，横幅不可达；实测确认），
      只保留可达的 `ModelConfigFileError` 一条路径。
- [x] `ui/src/SettingsView.tsx`：读取失败但**服务可达**时给出显式确认入口，确认后以空配置出图，
      使服务端「重新保存即可覆盖」的指引在桌面面真的可执行（原早退分支连表单带保存按钮一起藏掉，
      「坏文件不再是死路」的结论当时只在内核侧成立）；服务不可达时不提供该入口。
      `ChannelSettingsView` 缺失走 `BLANK_CHANNEL_VIEW` 基底，不伪造 `config_path`。
- [x] `ui/src/api.ts`：`invalid_config_file_overwritten` 按 OpenAPI 契约建模为可选（快照里
      `default: false` 且不在 `required`），读取处 `?? false` 归一。
- [x] spec delta 补三条场景：读不到≠未配置、读取失败后设置页仍可进入覆盖自救（含不可达时不给入口）。
- [x] 用例：`tests/test_model_supply.py`（OSError → 新类，且仍属基类、不属可覆盖类）、
      `tests/test_api_settings.py`（GET/PUT 文案含「无法读取」不含「补全」+ 原文件逐字节未动 +
      探测面同型顶替一例）、`tests/test_cli.py`（serve 在 unreadable 下 exit 1 与 corrupt 下横幅
      「非未配置」各 1 例，均打在可达路径上）、`ui/src/SettingsView.test.tsx`
      （覆盖自救入口出图 + 服务不可达时无入口，后者反向验证：撤掉确认门即红）。
- [x] 门禁：`ruff check/format` 全绿；`pytest` 全绿；ui `tsc`/`eslint`/`vitest` 全绿（终数见 HANDOFF 验证节）。
