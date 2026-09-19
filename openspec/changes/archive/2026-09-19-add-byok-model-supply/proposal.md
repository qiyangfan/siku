# 提案：模型供给全面 BYOK 端点化（删除进程内本地模型）

## Why

产品形态已定调（2026-09-18）：本地服务 + 全模型 BYOK 优先，对标 opencode 的供给模式。
当前检索链路把 bge-m3/bge-reranker 权重与 torch 运行时打进依赖与安装包（7.3GiB
sidecar、4.1GB DMG、冷启动 20s+），是唯一的体积与分发瓶颈；而问答回答本就 BYOK 上云，
检索模型没有任何理由停留在进程内形态。本地模型改由用户自部署端点提供（Ollama、vLLM、
LiteLLM、硅基流动等，暴露本地或远程端口），siku 只认协议。

进程内本地模型的"裁判"定位（为 golden set 提供参照基线）经评审否定：bge-m3 本身也是
可被替代的候选模型，由它当永久裁判是为现状辩解；真正能发现质量漂移的是**每个模型通道
自己的基线快照**（上游一变，该通道分数即动、闸门即响），不需要进程内参照物。

## What Changes

- 新增 `ApiEmbeddingProvider`（openai 兼容 `POST /embeddings`，批量、维度自动探测）与
  `ApiRerankerProvider`（`POST /rerank` 通用形：Jina/Cohere/硅基流动/LiteLLM 同构），
  与既有 `HttpxLlmProvider` 同构的 BYOK 形态。
- reranker 降为一等可选：`--reranker none` 时按 RRF 融合分数排序（Ollama 等端点无
  rerank API，这是本地自部署人群的必需品）；golden set 量化 rerank 的增量价值。
- 新增模型供给配置解析：CLI 参数 > 环境变量 > `~/.config/siku/config.toml`（0600，
  可存 key 明文或 key 环境变量名）> 无默认即报错。LLM/embedding/rerank 三通道同构。
- **删除进程内本地模型**：`LocalEmbeddingProvider`、`LocalRerankerProvider`、
  `siku.retrieve.local_models`、`retrieval` optional extra、torch/sentence-transformers
  依赖全部移除；检索质量闸门改为通道化基线（每通道一份基线快照，fingerprint 锚定
  fixture 与模型身份）。
- sidecar 瘦身：PyInstaller 剔除 torch/权重（7.3GiB → 预计几百 MB），产物无模型、
  无 HF 离线缓存逻辑。
- `index`/`search`/`serve`/`evaluate-retrieval` 全部接入端点参数与配置解析。

## 受影响决策

- ADR-0006：混合召回 + 重排架构与 golden set 闸门**不变**；"embedding 用本地模型"
  被本 change 修订为"模型供给一律 BYOK 端点"，由 ADR-0009 承接。
- ADR-0005：Extractor/Provider 可插拔接口的延伸——embedding/reranker 走同一模式。
- ADR-0002：本地可用形态（不依赖服务器部署）不受影响；本地模型经用户自部署端点获得。
- 新增 ADR-0009：模型供给 BYOK 化与通道化基线（记录决策、被否选项与代价）。

## 与项目路线的关系

属于 ROADMAP Phase 5 之后的打磨项（发布已按用户决策无限期推迟），是首个对外 tag 前
的必要瘦身：不完成本 change，桌面产物体积与分发形态不成立。Phase 5 桌面壳代码已合入
main 并保持挂起。

## Non-goals

- 不做账号、托管模型通道、计费（商业化阶段另行立项）。
- 不做云端多租户 SaaS、远端 vault 同步。
- 不改变 `/api/*` 响应字段、错误码与 OpenAPI 契约；问答语义不变。
- 不做 UI 设置中心：桌面端先以 config.toml 手工配置，UI 表单另行立项。
- 不实现 degraded 检索降级（FTS5-only 模式）：无 embedding 端点时按既有语义明确报错。
- 不删除 golden set 机制与既有 fixture；v0 基线文件保留为历史记录。
- 不提供模型下载管理器（用户经 Ollama 等工具自管模型）。

## 边界裁决

- 端点契约只认两类：`POST /embeddings`（openai 兼容，事实标准）与 `POST /rerank`
  （Jina/Cohere/硅基流动/LiteLLM 共同形）；不为任何单一厂商的特殊形做适配层，
  vLLM 等差异形经 LiteLLM 代理统一。
- 删除范围是"进程内运行方式"（代码与依赖），不是模型本身：bge-m3 在 Ollama/硅基流动
  上继续可用，参照质量永远经协议可达。
- golden set fixture 与 v0 基线文件不改动；新通道基线以独立文件并存，fingerprint
  机制防止跨通道误比。
- API key 可写入 0600 的 config.toml 或经环境变量间接提供；任何路径下 key 不得进入
  日志、索引元数据与基线文件。
