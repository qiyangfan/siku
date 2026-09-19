# 设计：模型供给全面 BYOK 端点化

## 目标拓扑

```text
siku 内核（桌面 sidecar / CLI 同一形态）
  ├─ LLM        → POST {llm.base_url}/chat/completions        （已有 HttpxLlmProvider）
  ├─ embedding  → POST {embedding.base_url}/embeddings        （新增 ApiEmbeddingProvider）
  ├─ reranker   → POST {rerank.base_url}/rerank               （新增 ApiRerankerProvider）
  │               或 none → RRF 融合分数直接排序
  └─ 配置来源优先级：CLI 参数 > 环境变量 > ~/.config/siku/config.toml > 报错
```

三通道同构：`base_url` + `model` + 凭证（`api_key` 明文或 `api_key_env` 间接）。
embedding/rerank 未配置时不是静默降级，而是带安装/配置指引的领域错误（与现有
`ModelNotAvailableError` 语义一致，但文案改为端点配置指引）。

## 端点契约

- **embedding**：`POST {base_url}/embeddings`，请求 `{model, input: [texts]}`，响应
  `data[].embedding`（openai 兼容事实标准；Ollama `/v1`、vLLM、LiteLLM、硅基流动、
  OpenAI 均适用）。维度在首次索引时以单条探针请求实测并写入索引元数据，支持
  `--embedding-dimensions` 显式覆盖（防端点返回维度与声明不符）。
- **rerank**：`POST {base_url}/rerank`，请求 `{model, query, documents: [texts],
  top_n}`，响应 `results[].{index, relevance_score}`（Jina/Cohere/硅基流动/LiteLLM
  共同形）。vLLM 的 score API 等差异形不在适配范围，经 LiteLLM 代理统一。
- **超时与重试**：与 `HttpxLlmProvider` 同策略；批量 embedding 按 `input` 分批
  （每批 ≤64 条）避免超长请求。
- 错误映射：连接失败/401/429/5xx → 复用既有领域错误族（`ProviderError`/
  `LlmProviderError` 映射路径），用户面文案中文、不含 key。

## 配置文件

`~/.config/siku/config.toml`（Linux/XDG；macOS `~/Library/Application Support/siku/
config.toml`；Windows `%APPDATA%\siku\config.toml`——与桌面数据根目录决策一致）：

```toml
[llm]
base_url = "https://api.deepseek.com"
model = "deepseek-chat"
api_key_env = "SIKU_LLM_API_KEY"     # 与 api_key 二选一

[embedding]
base_url = "http://127.0.0.1:11434/v1"
model = "bge-m3"
api_key = ""                          # 本地端点可空

[rerank]
base_url = "https://api.siliconflow.cn/v1"
model = "BAAI/bge-reranker-v2-m3"
api_key_env = "SILICONFLOW_API_KEY"
```

- 解析优先级：CLI 参数 > 环境变量 > config.toml > 无值报错。CLI 现有参数语义不变
  （`--api-key-env`/`--llm-base-url`/`--llm-model` 保持向后兼容）。
- 文件创建时 0600；读取不校验权限位但文档明示风险；key 不写入日志、索引元数据、
  评测基线与 OpenAPI。
- 解析由 pydantic-settings 承担（已是依赖），不引入新依赖。

## 通道化 golden set 基线

- `evaluate-retrieval` 新增 `--embedding-*`/`--rerank-*`/`--reranker none` 参数，
  评测 config 元数据扩展：`provider_kind`（api/rerank-none）+ `model` + `base_url`
  主机（不含 key、不含路径 query）。
- 基线文件按通道命名：`benchmarks/baselines/{channel}.json`（如
  `ollama-bge-m3.json`、`siliconflow-bge-m3-rerank.json`）；既有
  `retrieval-baseline-v0.json` 保留为历史记录不再参与比较（fixture fingerprint
  机制继续防止跨 fixture 误比）。
- 闸门语义不变：同通道当前分数 ≥ 该通道基线即通过；缺基线时必须 `--save-baseline`
  显式建立（沿用既有交互）。
- 本 change 验收要求：至少记录 Ollama（bge-m3，rerank=none）与一个云端
  embedding+rerank 通道的基线，并给出 rerank=none vs rerank 的分数对比。

## 删除清单

- `src/siku/retrieve/local_models.py`（LocalEmbeddingProvider/LocalRerankerProvider、
  维度探测、device 选择、`ModelNotAvailableError` 本地文案）。
- `pyproject.toml` 的 `retrieval` extra 与 dev 组注释中的本地模型语义；uv.lock 重锁。
- `tests/test_retrieve_local_models.py`；`tests/fakes.py` 的 fake provider **保留**
 （单测零外部依赖的基础设施，与 BYOK 不冲突）。
- `cli.py`/`app.py` 中 LocalProvider 的默认装配；`scripts/siku-sidecar.spec` 的
  torch/sentence-transformers hiddenimports；`build_sidecar.py` 的模型快照复制与
  `--skip-models` 参数（无模型可复制，参数删除）；`BUILD_INFO.json` 的 models 段。
- README/desktop.md 中 `uv sync --extra retrieval` 与内置权重叙事。

## 测试与验收策略

- Provider 单测：httpx mock（批切分、维度探针、401/429/超时映射、空 documents）。
- 配置解析单测：三级优先级、缺值报错文案、key 不泄漏（repr/日志断言）。
- RRF-only：现有检索测试以 fake embedding + none reranker 跑通排序稳定性。
- golden set：fixture 不变；Ollama 通道 + 一个云通道基线入库，报告 rerank 增量。
- 端到端：桌面 sidecar（瘦身版）+ Ollama 端点在本机完成 ingest→index→ask 全链路。
- 既有门禁全量执行：pytest/ruff/mypy/pre-commit/OpenAPI 快照零漂移/openspec strict。

## 风险与取舍

- 云端 embedding 的中文质量需数据裁决：通道基线给出 Recall@5/MRR@10 实测；若明显
  劣于历史 v0，用户可自选硅基流动的 BAAI/bge-m3 端点——模型不变，只是换了供给形态。
- 无 embedding 端点即无向量检索（BM25 单路不可用是既有架构，不因本 change 改变），
  报错文案必须可行动。
- rerank=none 会降低精度（尤其多候选混淆场景）：以通道基线数据呈现，由用户按端点
  能力选择；不静默。
- 删除是破坏性变更（CLI 默认通道消失、`--extra retrieval` 消失）：产品未发布，
  一次性切换成本最低的时机就是现在。

## 待确认项

- 硅基流动 rerank 端点对 `top_n`/返回排序的细节行为（实现时以实测为准，写入
  Provider 单测的契约样例）。
- Ollama `/v1/embeddings` 对批量 input 的分批上限（实现时探测定，Provider 内部
  保守取 64）。
- config.toml 是否需要 `siku config init` 脚手架子命令（倾向首版不做，文档给模板）。
