# 规划评审：模型供给全面 BYOK 端点化

## 已核对事实

- 产品形态已由用户定调（2026-09-18）：本地服务 + 全模型 BYOK 优先（opencode 模式）；
  本地模型由用户自部署端点提供（Ollama/vLLM/LiteLLM），siku 只认协议；进程内本地
  模型被明确否定。
- 问答回答（`/api/ask`）已将检索片段发往云端 LLM——"内容出本机"的口子已存在，
  embedding 端点化不打开新的隐私面，只是把同一条线贯彻一致。
- 当前检索链路的进程内 bge 依赖（torch + 4.4GB 权重）是 7.3GiB sidecar 与 4.1GB
  DMG 的全部来源；`sentence-transformers` 本就是 optional extra，删除不动核心依赖。
- golden set 的质量闸门价值在 fixture（问题-期望来源对）与回归纪律，不在某个具体
  模型；通道化基线（每通道一份快照）比"进程内 bge 永久裁判"更能发现真实漂移——
  产品实际运行在用户端点上，漂移发生在端点侧，进程内参照物对此不提供任何保护。
- Ollama 不提供 rerank API：自部署端点人群拿不到重排器，`reranker=none`（RRF-only）
  是必需品而非甜点；其精度代价由 golden set 数据量化。
- openai 兼容 `/embeddings` 是事实标准（Ollama/vLLM/LiteLLM/硅基流动/OpenAI）；
  `/rerank` 通用形覆盖 Jina/Cohere/硅基流动/LiteLLM，vLLM 差异形经 LiteLLM 代理。

## 评审结论

- 方案与宪法一致：数据主权（自持 schema 三件套）不变；引擎/Provider 可插拔（ADR-0005）
  正是本 change 的实现路径；架构红线 #1（UI↔内核只经 localhost HTTP）不受影响。
- 删除是本 change 的主体而非副作用：`local_models.py`、`retrieval` extra、torch 依赖
  一次性移除；产品未发布，破坏性切换成本处于全生命周期最低点。
- 通道化基线保留了 ADR-0006 的核心（golden set 是可执行规格 + 回归纪律），替换的只是
  基准的锚定方式——从"某个模型的绝对分数"改为"每个通道自己的历史分数"，闸门语义
  （不低于即通过、不得自动覆盖）原样继承。
- `reranker=none` 的精度损失是已知代价：不静默，由双通道基线数据显式呈现，用户按
  端点能力选择。

## 待确认与风险

- 硅基流动/LiteLLM rerank 响应的边界行为（top_n、平分排序）需实现期实测并固化为
  契约单测。
- 云端 embedding 的中文检索质量需通道基线数据裁决；若明显低于历史 v0 参照，用户
  可自选 BAAI/bge-m3 云端端点——模型可达性不因删除进程内形态而消失。
- 桌面首启无任何端点配置时，检索/问答均报配置指引错误：可接受（BYOK 产品的诚实
  行为），但文档必须给出一分钟可完成的 Ollama 路径。

## 规划阶段验证

- 本文件只记录规划评审，不声称已完成实现；实现完成后必须按 tasks.md 交付门禁补充
  删除完整性证据、通道基线数据与瘦身产物体积，再执行 openspec strict 双指令与项目
  全量门禁。

---

# 实现阶段评审（2026-09-19）

## 实现证据

### 1. 删除完整性 grep

- `grep -rn "local_models|LocalEmbeddingProvider|LocalRerankerProvider|extra retrieval"
  src tests scripts pyproject.toml .github` → **零命中**。
- `retrieval` extra 已从 pyproject 移除；lancedb 升为核心依赖（ADR-0003 三件套，
  dev 组不再单列）；uv.lock 重锁后 torch/sentence-transformers 仅存于 ingest-pdf
  extra 的 docling 传递依赖（合法可选 extra，不进核心与 sidecar）。
- `uv sync` 实测卸载本机 torch 系运行时（venv 内已无 torch）。
- 附带清理：release.yml 的 HF 模型缓存步骤/步骤名/头注、vector_store 与
  errors.py 的过期 docstring。

### 2. 配置优先级矩阵（resolve_*，单测锚定 tests/test_model_supply.py）

| 通道 | CLI 层 | env 层 | config.toml 层 | 全层缺失行为 |
|---|---|---|---|---|
| llm | `--api-key-env` `--llm-base-url` `--llm-model`（现为 None 缺省，语义向后兼容） | `SIKU_LLM_*` | `[llm]` | 回退 DeepSeek 缺省（既有语义）；key 在调用时校验 |
| embedding | `--embedding-base-url/model/api-key-env/dimensions` | `SIKU_EMBEDDING_*` | `[embedding]` | `ModelNotAvailableError` + config 路径与 CLI 示例指引，不回退内置端点 |
| rerank | `--reranker api\|none` `--rerank-*` | `SIKU_RERANK_*` | `[rerank]` | 显式 api 模式报同上指引；自动模式降为 reranker=none 并在输出明示 |

- 空串与未设置等价（`_drop_blank`，与 SIKU_LOG_LEVEL 同口径）；config.toml 的
  `api_key = ""`（本地端点）读作无 key。
- 0600：`save_config` 以 `os.open(mode=0o600)` 创建、重写后 `chmod` 收敛；
  测试断言 `stat.S_IMODE == 0o600`（创建与放宽后重写两条）。

### 3. key 不泄漏断言

- `SecretStr` 承载：repr/str 掩码断言（test_key_never_appears_in_repr_or_str）。
- provider 错误消息不含 key（401/403 断言，embedding/reranker 各一）。
- `save_config` 日志仅记模型名；`channel_slug` 无 key 物料断言。
- 索引元数据（IndexModelMetadata）与评测基线 config 只含模型 id/维度/端点主机。
- 评审 P2-1 修复：load_config 的 ValidationError 只保留字段路径与错误类型，
  不再内嵌 input_value（防用户误写未加引号的 key 值经 DEBUG 日志泄漏）。

### 4. 瘦身产物体积与冒烟

- 本机 macOS arm64 实测：**7.3 GiB → 305 MiB**（`BUILD_INFO.json` 记录
  `models_included: false`、uv_lock_sha256、无 torch 系包）。
- dev 环境全链路：ingest → index（BYOK 端点 + 维度覆盖 + 通道标签）→ search
  （reranker=none 命中且 rerank_score 回填 hybrid）→ serve `/api/health`、
  `/api/search`、`/api/ask`（openai 兼容契约端点，HTTP 200 语义正确）。
- 冻结二进制：`siku-sidecar version`、serve + health 200、未配置 embedding 时
  index/search 返回可行动中文指引。
- **待外部输入**：真实 Ollama/云端通道的桌面全链路冒烟（本机无 Ollama、无云端
  key），由 HANDOFF 下一步 #2 承接。

### 5. 门禁

pytest 492 passed；ruff check/format 通过；mypy 92 文件零错误；pre-commit 全过；
openspec strict 双指令（change valid + specs 7/7）；OpenAPI 快照 diff 为空。

## 独立子代理评审结论与处置

**APPROVE_WITH_FIXES**（P0=0，P1=3，P2=9）。逐 Scenario 核验 spec delta 全满足；
架构红线无违反；未完成项标注诚实。

- **P1-1 serve 每请求重建 provider 泄漏连接池** → 已修：`_supply_search_factory`
  首次装配后进程内缓存复用；回归测试断言 provider 只构造一次。
- **P1-2 serve 默认装配链路零测试** → 已修：新增 tests/test_model_supply_api.py
  5 项（未配置指引 503、装配链路命中、缓存、rerank 缺省 RRF-only、dimensions 透传）。
- **P1-3 release.yml 模型时代残留** → 已修：删除 HF 缓存步骤，修正步骤名与头注。
- **P2 已修 7 项**：P2-1（ValidationError 脱敏）、P2-3（索引元数据补
  embedding_channel_host，仅追溯不参与 matches_provider）、P2-4（search/serve 补
  `--embedding-dimensions`）、P2-5（check_channel_identity：显式 --baseline 指到
  他通道硬失败；历史 v0 基线仅保留指纹门禁）、P2-6（通道字段/明示输出补测）、
  P2-7（serve 启动明示三通道 + 文档措辞修正）、P2-8（HANDOFF 整体重写同步）。
- **P2 上报不改 1 项**：P2-2（端点非 4xx 错误体回显响应前 200 字符）与既有
  HttpxLlmProvider 同模式，统一收紧属跨模块决策，建议后续 change 一并处理。
- **P2-9 已同步**：openspec/project.md 红线 1 措辞扩展至 BYOK 模型 API（LLM/
  embedding/rerank），文头 ADR 范围更新为 0001~0009，与 ADR-0009 互证。

## 遗留与归档条件

- 双通道基线入库（Ollama bge-m3 rerank=none + 一个云端 embedding+rerank 通道）
  与 rerank=none vs rerank 分数对比：**阻塞于外部端点**（见 tasks.md）。
- 本 change 的 archive 与主 spec sync：按 HANDOFF 排序，待发布解禁、三平台冒烟
  闭环后与 add-tauri-desktop-shell 一并执行。

## 验收裁决（用户，2026-09-19）

- **双通道基线入库豁免**：Ollama 为稳定主流供给方案，与第三方厂商无本质区别，
  不因缺本机实测阻塞验收。实现与复现路径已就绪（`benchmarks/README.md`），
  通道基线可在任意具备 Ollama/云端 key 的环境随时补录。
- 随本裁决，design.md「验收要求：至少记录双通道基线」由产品所有者豁免；
  其余门禁（pytest/ruff/mypy/pre-commit/openspec strict/OpenAPI 零漂移）全绿不变。
- 据此本 change 全部任务到达终态，执行 archive 并同步主 spec
  （同日裁决：现阶段仅 macOS 为验收平台，Windows/Linux 冒烟随发布解禁另行安排）。
