# 任务清单

## Provider 与配置层

- [x] 新增 `ApiEmbeddingProvider`：openai 兼容 `/embeddings` 批量调用、分批（≤64）、
      维度探针（首索引实测 + `--embedding-dimensions` 覆盖）、超时与 401/429/5xx
      领域错误映射；httpx mock 单测。（`retrieve/api_providers.py`，13 项单测）
- [x] 新增 `ApiRerankerProvider`：`POST /rerank` 通用形调用、top_n、空 documents、
      错误映射；httpx mock 单测（含与硅基流动/LiteLLM 响应样例的契约用例）。
      （同文件，12 项单测）
- [x] `SearchService` 支持无 reranker 的 RRF-only 排序路径（确定性次级排序不变）+
      单测。（reranker=None 时按 hybrid 降序 + chunk_id 升序；rerank_score 回填
      融合分数保持契约零漂移，4 项新单测）
- [x] 新增分层配置解析（pydantic-settings）：CLI > 环境变量 > 平台 config.toml；
      缺值报错文案；0600 创建/重写；key 不入日志与持久化产物（repr/日志断言单测）。
      （`siku/model_supply.py`，17 项单测；llm 通道保留 DeepSeek 缺省兼容既有
      CLI 语义，embedding/rerank 无内置端点）

## 接线与切换

- [x] `siku index`/`search` 接入 embedding/rerank 端点参数与分层配置；未配置时给出
      可行动指引；移除 LocalProvider 装配。（`--embedding-*`、`--reranker api|none`、
      `--rerank-*`；graph/wiki 的 LLM 参数改为分层解析 + DeepSeek 缺省兼容；
      mock 端点端到端冒烟通过）
- [x] `siku serve` 透传 embedding/rerank 配置到 `create_app` 工厂（`/api/search`、
      `/api/ask` 行为不变，OpenAPI 快照零漂移）。（contract --refresh diff 为空）
- [x] `siku evaluate-retrieval` 参数化模型通道；评测 config 扩展
      `provider_kind`/`model`/`base_url` 主机；基线文件按通道命名
      （`benchmarks/baselines/{channel}.json`）；v0 基线退役为历史记录。
      （`--channel` 可显式覆盖派生 slug；rerank 模式与通道在输出中明示）
- [x] 删除 `siku/retrieve/local_models.py`、`retrieval` extra、
      `tests/test_retrieve_local_models.py`，重锁 uv.lock；`tests/fakes.py` 保留。
      （lancedb 升为核心依赖（ADR-0003 三件套），dev 组不再单列；torch 系仅存于
      ingest-pdf extra 的 docling 传递依赖；隔离测试改写为 BYOK 语义）

## 打包与文档

- [x] sidecar 瘦身：`siku-sidecar.spec` 去除 torch/sentence-transformers、
      `build_sidecar.py` 删除模型快照复制与 `--skip-models`；本地构建验证体积
      （目标数百 MB）与 serve→ask 全链路（Ollama 或云端端点）。
      （本机 arm64 实测 305 MiB，models_included=false；ingest→index→search→
      serve→ask 全链路对 openai 兼容端点契约实测通过，冻结二进制 serve/health/
      未配置指引通过；**真实 Ollama/云端通道的桌面冒烟待外部端点**，由 HANDOFF
      下一步 #2 与双通道基线任务承接）
- [x] 新增 ADR-0009（模型供给 BYOK 化与通道化基线），ADR-0006 状态行加修订注记。
      （proposal 阶段已写入并复核：决策/理由/被否选项/代价/复核信号齐备）
- [x] 更新 README、`docs/desktop.md`、`ui/README.md`：BYOK 端点配置指引
      （Ollama 本地端点示例 + 云端示例）、config.toml 模板、删除内置权重叙事。
      （另同步 `benchmarks/README.md` 的通道化基线复现流程）

## 交付门禁

- [x] 全量门禁：pytest/ruff/format/mypy/pre-commit/openspec strict 双指令/
      OpenAPI 快照零漂移。（pytest 481 passed；ruff check+format 通过；mypy 91
      文件零错误；pre-commit 8 hooks 全过；openspec change valid + specs 7/7；
      OpenAPI 快照 diff 为空）
- [x] golden set 双通道基线入库：Ollama（bge-m3，rerank=none）+ 一个云端
      embedding+rerank 通道；报告 rerank=none vs rerank 的分数对比。
      **【用户裁决豁免，2026-09-19】** Ollama 为稳定主流供给方案，与第三方厂商
      无本质区别，不因缺本机实测阻塞验收；实现与复现路径已就绪，任何装有
      Ollama/云端 key 的环境可随时按 `benchmarks/README.md` 补录通道基线。
- [x] 独立评审（review.md 补实现证据：删除完整性 grep、配置优先级矩阵、key 不泄漏
      断言、瘦身产物体积）；完成后才允许 archive 并同步主 spec。
      （独立子代理结论 APPROVE_WITH_FIXES：P0=0/P1=3/P2=9；P1 全修、P2 修 7 项、
      上报 1 项（P2-2 端点错误体回显，沿既有 HttpxLlmProvider 模式）；处置明细
      见 review.md「实现阶段评审」。archive + 主 spec sync 按 HANDOFF 排序待
      发布解禁后执行）
