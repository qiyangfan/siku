# 设计：CI 版 E2E 冒烟

## 定位一句话

CI 版 E2E = **接线回归门禁**：真实 serve 进程 + 确定性 fake 端点 + 五段编排，只验证
「拼起来还通不通」。质量归 golden set（ADR-0006），组件契约归 862 分段单测，冻结产物
形态归 `smoke_clean_env.py`（ADR-0013）。四个资产互不冒充。

## 确定性设计（入闸前提）

一切模型调用 canned / 确定性，无网络无密钥，断言稳定：

- **fake 三通道端点服务**（`tests/e2e/fake_channels.py`）：pytest 进程内线程起
  FastAPI + uvicorn（均为核心依赖），绑 ephemeral 端口。三个端点按 ADR-0012 协议应答：
  - `POST /v1/chat/completions`：罐头响应。图谱抽取 / wiki 摘要请求返回固定 JSON
    （实体/社区 → 确定图谱）；ask 型请求**从 prompt 的检索上下文里抽取种子标记回显**
    ——回显标记出现在答案里 = 检索上下文确实喂到了 LLM，这是接线证明而非内容证明。
  - `POST /v1/embeddings`：确定性向量，复用 `tests/fakes.py` `_deterministic_vector`
    的 hash 思路（同文本恒同向量，维度与 serve 配置一致）。
  - rerank 端点：固定排序罐头。
- **种子语料**：复用 `tests/document_fixtures.py` 生成思路——1 个 markdown（种子事实
  唯一来源）+ 1 个小 PDF（钉住 10-02 大改的 pypdf 路径）。种子事实写入 markdown，
  断言全部锚定它。
- **确定性自检**：本地连续跑 3 次结果逐字段一致才允许进 blocking；任何时序抖动先修
  再上（会偶发红的 E2E 进门禁是负资产）。

## 注入与进程形态

serve 子进程，通道经既有 CLI 契约注入（零新机制）：

```
siku serve --port <free-port> --vault <tmp>/vault --data-dir <tmp>/data \
  --llm-base-url http://127.0.0.1:<fake>/v1 --api-key-env SIKU_E2E_KEY \
  --embedding-base-url http://127.0.0.1:<fake>/v1 --embedding-api-key-env SIKU_E2E_KEY \
  --rerank-base-url http://127.0.0.1:<fake>/v1 --rerank-api-key-env SIKU_E2E_KEY
```

- 端口：内核分配 ephemeral（fake 端点与 serve 各自绑 0 取实分配），杜绝竞态。
- boot：轮询 `GET /api/health`，timeout 60s（`smoke_clean_env.py` 先例）。
- teardown：终结整个进程组，防孤儿（复用 `smoke_clean_env.py` 的 signal 清理模式；
  本件在 pytest fixture finalizer 里做，CI/本地同样生效）。
- fake 端点不校验 key，环境变量给占位值即可——BYOK 校验属单测领地。

## 五段编排与断言清单

| 段 | 端点 | 断言（只测接线） |
|---|---|---|
| 1 boot | `GET /api/health` | 200，就绪字段可用（三通道已配置，不落 `invalid`） |
| 2 ingest | `POST /api/library/ingest` → 轮询 `GET /api/library/jobs/{id}` | 作业成功（真实作业槽 + 轮询调度被走到）；`GET /api/library` 列出种子文档且 `source_hash` 在场；**同文件重摄取 → 不翻倍**（红线 2 幂等抽查） |
| 3 search | `POST /api/search` | 种子文档命中且引用来源正确（embedding + rerank 通道接线） |
| 4 graph + wiki | `POST /api/graph`、`POST /api/wiki`、`GET /api/wiki/entries` | 实体数 = 罐头抽取数；wiki 条目在场（摄取 → LLM 抽取 → parquet → serve 读回全链） |
| 5 ask | `POST /api/ask` | 答案非空且**含上下文回显标记**；`references` 指向种子文档（检索 → 上下文 → LLM → 引用全链） |

每段断言独立、失败报告指明断在哪段——修复定位以「段」为单位。产物文件
（SQLite/LanceDB/parquet）存在性作为段 2/4 的辅助断言，但不校验内部格式（格式契约归
分段单测）。

## CI 门禁策略

- **job `e2e`**：ubuntu-latest、Python 3.12 单版本（不进 3.14 矩阵——接线回归与语言
  版本哨兵是两件事，ADR-0008 域不动）、timeout 15min、`uv sync --locked` +
  `uv run pytest -m e2e`。预期分钟级。
- **changes 门控**：`changes` job 新增 `e2e` 输出，匹配
  `(^src/|^tests/e2e/|^pyproject\.toml$|^uv\.lock$)`，判定失败 fail-open（宁可多跑
  不漏跑，与现行 sidecar/rust 门控同一哲学）。
- **直接 blocking**：确定性前提已由设计成立（全罐头、无网络、无密钥），不设 nightly
  过渡期。**降级预案**：上线首周任何 flake 记 issue 修稳；若连续不稳，临时降为
  `workflow_dispatch`/nightly 手动触发，修稳后回 blocking——处置决策记 review.md。
- **默认排除**：`pyproject.toml` 注册 `e2e` marker + `addopts -m "not e2e"`，既有
  全量 `uv run pytest` 门禁（两版本矩阵）零感知、时长不变；CLI `-m e2e` 覆盖 addopts
  进本 job。

## 收敛与卫生

- tmp vault/data 目录用 pytest `tmp_path` fixture，用后即弃。
- serve 单任务槽天然串行化段内操作，编排无需自己加锁；job 间由 CI 隔离。
- fake 端点线程随 fixture finalizer 关停；断言失败时先收进程再收线程，保证失败路径
  也不留孤儿。

## 验证策略

1. 本地 `python -m pytest -m e2e` 绿 ×3（确定性自检）。
2. 本地 `python -m pytest`（默认排除）全量绿，确认既有门禁零感知。
3. 推分支触发 CI：e2e job 绿；改动无关路径时 e2e job 被门控跳过（验证 fail-open 与
   门控两面）。
4. 人为断一处接线（如改错 fake 端点路径）确认会红——门禁必须能抓到它声称抓的东西。

## 风险与对策

| 风险 | 对策 |
|---|---|
| 段间契约漂移导致 e2e 红 | 这正是它的职责，红即价值；按段定位修复 |
| CI runner boot 慢 | health 轮询 timeout 60s 先例；种子语料小，摄取秒级 |
| 端口/进程竞态致偶发红 | ephemeral 端口 + 进程组终结 + 确定性自检 3 连绿才合入 |
| pypdf 对生成 PDF 解析不稳 | 种子 PDF 走 `document_fixtures.py` 既有生成器（reportlab，真实解析器可读） |
