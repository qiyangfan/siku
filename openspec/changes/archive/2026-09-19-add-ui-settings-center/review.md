# 实现评审：桌面 UI 设置中心（BYOK 三通道端点配置表单）

评审时间：2026-09-19（apply 完成后）。本记录覆盖 tasks.md 交付门禁要求的三类证据：
凭证边界、原子写与权限保持、缓存失效与告警语义；以及冒烟结果。

## 实现落点

- 领域模块 `src/siku/api/settings.py`：掩码视图 / 合并 / 校验 / 探测 / 告警；
  路由挂进 `api/app.py`（`GET/PUT /api/settings`、`POST /api/settings/test`）。
- `model_supply.save_config` 升级为原子替换（mkstemp 0600 + fsync + `os.replace`，
  失败清理临时文件）。
- `create_app` 三参（`llm_base_url/llm_model/llm_api_key`）收敛为 `llm_supply`
  （CLI 层原样透传）；LLM 默认工厂改**每请求现解析**（CLI > env > config.toml 现读）。
- 检索装配缓存 `_SearchSupplyCache`：带锁 `get/invalidate`，失效时
  `SearchService.close()`（新增，释放 provider 连接池）。
- UI：`SettingsView.tsx` 三通道分区表单 + `App.tsx` 内 tab 导航（无新依赖）；
  `api.ts` 增设置三端点封装。CORS `allow_methods` 增 `PUT`。

## 契约与决议符合性

- **决议 #1（契约形状）**：GET 返回文件层掩码视图 + `config_path` +
  `env_overrides` 标注；PUT 通道省略 = 不变、字段省略 = 保持、null/空白 = 清空、
  非空 = 设置；校验失败 422 `invalid_settings` 且不落盘（测试
  `test_invalid_base_url_returns_422_without_writing`、`test_field_semantics_keep_clear_and_set`）。
  新增稳定错误码仅 `invalid_settings` 一个；test 失败复用既有错误码族（503）。
- **决议 #2（rerank 可选 / 告警）**：rerank 段留空 = none（写空即 RRF-only，
  无 enabled 字段）；告警比对基准 = 索引元数据 `embedding_model_id` vs 保存后
  有效解析模型（env 层参与、CLI 层不参与），索引缺失/损坏静默跳过，绝不阻塞保存
  （`TestEmbeddingChangeWarning`）。
- **决议 #3（写入策略）**：同目录临时文件（0600）+ fsync + `os.replace`；
  替换失败既有文件不破坏、无临时文件残留（`test_atomic_replace_failure_keeps_existing_file`、
  `test_save_config_leaves_no_temp_files_behind`）；last-writer-wins，无文件锁。

## 凭证边界证据

- GET/PUT 响应任何字段不含 key 明文，key 仅以 `api_key_set` 布尔标记
  （`test_masked_view_never_echoes_key`、`test_put_writes_channels_and_response_stays_masked`）。
- 请求体不落日志：PUT 携带 key 后 `caplog` DEBUG 全量无 key
  （`test_request_body_never_reaches_logs`）；探测失败同样断言
  （`test_probe_never_persists_or_leaks`）。
- 探测不回显上游错误体：错误消息仅由错误类 + 状态码构造，401/429 剧本响应中无
  上游 body 内容（五剧本参数化断言）；路由日志只记 `error_class`。
- 探测不持久化：调用前后 config.toml 字节一致（`test_probe_never_persists_or_leaks`）。
- 冒烟复验：真实 serve 进程日志 `grep` key 明文 0 命中；UI 全页文本 0 命中；
  表单 key 输入框 password 类型、值恒空、以「已设置——留空保持不变」占位。

## 缓存失效与免重启证据

- 集成测试：保存新 embedding 模型后，下一次检索按新配置重建 provider（build 计数
  1→2，检索返回 409 `model_config_mismatch` 证明用了新模型——元数据仍是旧模型，
  指引全量重建），全程无重启（`test_settings_write_rebuilds_search_provider_without_restart`）。
- LLM 通道：PUT 后下一次问答的 provider 以新 base_url/model 构造
  （`test_llm_channel_settings_apply_without_restart`）。
- 注入 `search_service_factory` 的测试路径无缓存可失效，语义不变
  （`test_model_supply_api.py` 全绿）。

## 冒烟记录（review 门禁）

形态：serve（生产 `create_app`，仅把配置路径指向 /tmp 冒烟目录，不触碰用户真实
config.toml）+ 构建版 `ui/dist` + 本机回环 fake BYOK 端点（chat/embeddings/rerank
三件套）+ 浏览器驱动构建版 UI。**Tauri 壳内真实端点的桌面手工冒烟未执行**（需真实
BYOK 环境，沿 desktop-shell 豁免先例留待用户按需执行，见 HANDOFF 触发台账）。

| 步骤 | 结果 |
| --- | --- |
| 空配置启动 → 设置视图三通道表单 | 正常渲染，占位与说明文案正确 |
| 表单填写 llm/embedding/rerank 三通道（含 key）→ 保存 | 「设置已保存，无需重启即可生效。」 |
| 保存后 config.toml | 0600，三通道段与表单一致，key 仅在文件层 |
| 不重启直接问答（curl 与 UI 各一次） | 200，回答带 C1 引用，模型 fake-llm |
| LLM 通道「测试连接」 | 「连接成功，耗时 14 ms。」 |
| embedding 模型改为 fake-embed-b → 保存 | 成功 + 显著黄色告警卡（旧→新身份与 `siku index --rebuild` 指引），不误导为失败 |
| 改回 fake-embed → 保存 | 告警消失 |
| 刷新页面 | key 输入框为空 + 「已设置」占位，页面无 key 明文 |
| 窄窗口 390px | 字段纵向堆叠，无横向溢出（scrollWidth == clientWidth） |

## 门禁结果（2026-09-19 复验）

- pytest 519 passed（全量，含新增 20 项设置契约测试与 save_config 原子写回归）。
- ruff check / ruff format、mypy（94 文件零问题）、pre-commit 全绿。
- OpenAPI 快照显式刷新：新增仅 `/api/settings`（GET/PUT）与 `/api/settings/test`，
  既有路径零漂移（与 HEAD 快照逐 path 比对）。
- `openspec validate --changes --strict` 3/3 通过；`npm run lint/test/build` 全绿
  （vitest 12 项，含 App 入口可达性测试）。

## 遗留与待确认

- Tauri 壳内真实端点手工冒烟：待用户执行（上表自动化冒烟已覆盖同一 create_app
  与同一静态产物的全链路，壳层仅差 Tauri 窗口本身）。
- PUT 合并在极端并发（多端同时写同一 config.toml）下为 last-writer-wins，无告警；
  单用户桌面场景按决议接受。
- 探测对付费端点产生一次最小计量请求（每通道每次点击一条），已由固定探针负载
  最小化。
