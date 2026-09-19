# HANDOFF — siku 交接文档

> **接驳点，非常驻知识库。** 常驻知识分属四层：宪法 `openspec/project.md`、协作规范
> `AGENTS.md`、路线 `docs/ROADMAP.md`、相关决策 `docs/adr/`。本文件每次交接整体重写，
> 只写接手者马上需要的状态。

- **更新时间**：2026-09-19（第八次，add-desktop-library 已归档提交，工作树干净）
- **仓库**：`~/siku` → github.com/qiyangfan/siku（私有；SSH 推送，gh keyring 认证）

## 现状

- **`add-desktop-library` 已归档**（`changes/archive/2026-09-19-add-desktop-library/`）：
  五端点（清单 / 导入任务 / 进度 / 协作取消 / 确认重建）+ 进程内单任务槽 + React
  资料库视图；http-api/web-ui spec 增量已入主 specs（strict 8/8）。批次按模块分四笔
  入库（feat(api)/feat(ui)/chore(openspec)/docs），工作树干净、未推送远端。
- **下一个 apply 对象：`add-browse-graph-wiki-views`**（浏览·图谱·wiki 视图）。
  proposal 全件已提交；配模型 ✅ → 进资料 ✅ → **看知识**为上手链路最后一环。
- 门禁基线（归档后复验）：pytest **546**、ruff check/format、mypy、pre-commit、
  openspec strict（changes 1/1 + specs 7/7）、npm lint/test/build 全绿。
- Release 无限期禁用不变，`v0.1.0` tag 遗留未删。

## 已知坑

- **资料库任务**：`LibraryJobManager`（`siku/api/library.py`）daemon 线程单任务槽，
  状态只存内存，重启即失；`create_app(index_runner=...)` 为索引衔接注入点，缺省
  每任务现解析 embedding 通道。清单索引态对照**附件当前哈希**（非投影哈希）；
  上传幂等靠确定性暂存路径，改命名即破坏 skip——细节见归档件 design.md/review.md。
- serve 供给装配：LLM 三工厂**每请求现解析**；检索走 `_SearchSupplyCache`，设置 PUT
  后 `invalidate()`。测试注入点 `build_embedding_provider/build_reranker_provider`
  与 `index_runner`；显式传 `search_service_factory` 则无缓存语义。
- 设置合并语义、provider 异常翻译口径、`base_url_host` 定居 retrieve/providers.py、
  换 embedding 模型必须全量重建、`mypy` 不带路径参数、冻结入口保留
  `freeze_support()`、端点错误体不回显——沿袭既有归档件，不赘述。
- 手工冒烟缺真实模型时：openai 兼容 mock（/embeddings + /chat/completions）即可跑通
  资料库全链路，做法见归档件 review.md 冒烟段。

## 触发型（不主动做，全在 ROADMAP 台账有账）

Phase 6 签名与自动更新（等发布解禁决策）；Windows/Linux 实机冒烟（等发布解禁，清单
见 docs/desktop.md）；双通道基线补录（等 Ollama/云端 key 环境）；设置中心与资料库
Tauri 壳内真实端点界面级冒烟（等真实 BYOK 环境；serve 级全链路已在归档 review.md 记账）。
