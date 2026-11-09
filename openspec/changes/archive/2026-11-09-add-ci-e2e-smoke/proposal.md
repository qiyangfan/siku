# 提案：CI 版 E2E 冒烟——真实 serve 进程五段接线回归门禁

## Why

三层测试结构里有一层至今无人管：862 个分段单测（进程内 `TestClient`，全 fake）验证组件
契约，golden set 验证检索质量，但**「五段拼起来的真实 serve 进程还通不通」没有任何东西
兜着**。这一层结构上够不着三类问题：

1. **跨段状态契约漂移**。分段单测用的都是手工构造的「上一段输出」夹具，真实的段间产物
   形状漂移时夹具不会知道——会出现「862 个测试全绿而真实链路已断」。事实核查：最近一次
   全链冒烟证据是 2026-09-24，早于 10-02 摄取运行时大改（`b508a5c`：pypdf/Office 进核心、
   图谱/wiki 快照失效、filelock 互斥）；连既有冒烟脚本 `scripts/smoke_clean_env.py` 的
   最后一次改动也停在该 commit——**这个回归窗口至今裸奔**。
2. **真实 boot 路径**。serve 进程启动、分层 config 解析、路由挂载、单任务槽、作业轮询
   调度只在真进程里显形，进程内 client 覆盖不到。
3. **公开后的变更节奏**。公开 = 陌生人 issue 驱动补丁 + 例行依赖升级，变更频率上升而
   测试面不变；没有可复跑物，每次验收退回「手动跑一次真通道」，已证明会退化成一次性证据。

边际成本低：确定性 fake 基建已有雏形（`tests/fakes.py` 的 hash 确定性向量），serve 原生
暴露三通道 `--llm-base-url` / `--embedding-base-url` / `--rerank-base-url` 注入点
（BYOK 契约，ADR-0009/0012），**无网络无密钥即可全链**。

## What Changes

- **新增 `tests/e2e/`**：一个 fake 三通道端点服务（openai 兼容 chat completions +
  embeddings 确定性向量 + rerank 固定序，全部罐头响应，跑在 pytest 进程内线程）+
  一个真实 `siku serve` 子进程的五段编排冒烟（boot → ingest → search → graph/wiki →
  ask）+ `e2e` pytest marker。
- **确定性是入闸前提**：所有模型调用 canned/确定性 → 断言稳定 → 直接进 blocking 门禁。
- **CI 门禁**：`ci.yml` 新增 `e2e` job（changes 门控：`src/`、`tests/e2e/`、
  `pyproject.toml`、`uv.lock` 变化才跑，fail-open 与现行哲学一致）；既有全量 pytest
  默认排除 e2e（`addopts -m "not e2e"`），不拖慢现有门禁。
- **断言边界钉死**：只断「管道通、产物在、答案含上下文回显标记且引用指向种子文档」；
  重摄取幂等抽查（红线 2）。质量断言零越界。
- 种子语料复用 `tests/document_fixtures.py` 生成思路（markdown + 小 PDF，PDF 钉住的
  正是 10-02 大改的 pypdf 路径）。

## 受影响决策

只引用、不修改：ADR-0001（双语言栈——e2e 走 serve 公开 HTTP 面，不碰内核内部）、
ADR-0002（三阶段发布——公开节奏是本件防线的依据）、ADR-0006（检索质量与 golden set——
质量断言不越界，两套资产互补不竞争）、ADR-0009（BYOK——`--*-base-url` 注入即既有契约
的消费面）、ADR-0012（LLM 多协议——fake 端点按协议罐头应答）、ADR-0013（轻量默认摄取
与 sidecar——`smoke_clean_env.py` 继续手动负责冻结产物形态，本件负责开发态管线接线，
互补不替代）。

## Impact

文件面：新增 `tests/e2e/`（conftest + fake 端点 + 编排用例），`pyproject.toml`
（注册 marker + addopts 排除），`.github/workflows/ci.yml`（新 job + changes 门控输出）。
零新增依赖（fastapi/uvicorn/httpx 均已在核心）。验证面：既有全量 pytest 用例数不变、
时长不变；e2e job 分钟级、无密钥；对用户行为零可观察变化。

## Non-goals（不做清单）

- 不做检索/生成质量断言（Recall/MRR、答案质量归 golden set + 通道基线，ADR-0006 领地）。
- 不做浏览器/GUI/Tauri 黑盒冒烟（第四层继续低频手工，本件不碰 UI 进程）。
- 不替代 `smoke_clean_env.py` 的冻结 sidecar 干净环境冒烟（该件继续发布期手动执行；
  本件是开发态管线接线，两者验证对象不同）。
- 不测 CLI / MCP 面（v1 只锁 serve HTTP 编排这一种部署形态；CLI/单测已各自覆盖）。
- 不做段间 schema golden 快照契约测试（值得以后补，是补充不是替代，另行开件）。
- 不做耗时/性能断言；不做目录同步（scan 轮询）编排，留待后续按需扩展。
- 不新增任何依赖、不引入网络与密钥（门禁确定性前提）。
- 不改任何 spec 级行为：纯测试基建与 CI 编排，由 `.openspec.yaml` 声明 `skip_specs: true`
  （先例：`2026-10-18-upgrade-dependencies-2026-10`）。

## 与项目路线的关系

纯工程基建，不占排序队列的产品项；执行前已对齐 `docs/ROADMAP.md`（排序队列清空状态），
且为 owner 授权的管理员建议落地。支撑 ADR-0002 阶段三公开的变更节奏防线。归档时回写
ROADMAP 勾稽。
