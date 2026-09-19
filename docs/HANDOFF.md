# HANDOFF — siku 交接文档

> **接驳点，非常驻知识库。** 常驻知识分属四层：宪法 `openspec/project.md`、协作规范
> `AGENTS.md`、路线 `docs/ROADMAP.md`、相关决策 `docs/adr/`。本文件每次交接整体重写，
> 只写接手者马上需要的状态。

- **更新时间**：2026-09-19（第六次，设置中心已归档，全部工作已提交，工作树干净）
- **仓库**：`~/siku` → github.com/qiyangfan/siku（私有；SSH 推送，gh keyring 认证）

## 现状

- **树干净、全部已提交**：BYOK 端点化（Phase 5+）与设置中心（Phase 5++ 第 1 项）两大
  批次均按模块分批入库（feat/chore/docs 中文提交），归档件与主规格同步随之入库。
- **`add-ui-settings-center` 已归档**（`changes/archive/2026-09-19-add-ui-settings-center/`）：
  三端点 + 原子写 0600 + 免重启生效 + React 设置视图；http-api/web-ui spec 增量已入
  主 specs（strict 7/7）。Tauri 壳内真实端点手工冒烟在触发器台账有账。
- **下一个 apply 对象：`add-desktop-library`**（桌面资料管理），从 tasks.md「约束冻结」
  三项做起（决议落 design.md）；其后 `add-browse-graph-wiki-views`。两个 proposal 全件
  已提交，apply 前可按用户评审意见修订。排序：配模型 ✅ → 进资料 → 看知识。
- 门禁基线（2026-09-19 复验）：pytest 533、ruff check/format、mypy、pre-commit、
  openspec strict（changes 2/2 + specs 7/7）、npm lint/test/build 全绿。
- Release 无限期禁用不变，`v0.1.0` tag 遗留未删。

## 已知坑

- serve 供给装配：LLM 三工厂**每请求现解析**（`create_app(llm_supply=CLI 层)`，CLI >
  env > config.toml 现读）；检索走 `_SearchSupplyCache`，设置 PUT 后 `invalidate()`。
  测试注入点 `siku.api.app.build_embedding_provider/build_reranker_provider`；显式传
  `search_service_factory` 则无缓存语义。
- 设置合并语义（归档 change design.md 决议 #1）：通道省略 = 不变；字段省略 = 保持；
  null/空白 = 清空；`api_key` 只写不回显，UI 未触碰不上传。
- provider 请求异常统一翻译口径：`except (httpx.HTTPError, httpx.InvalidURL,
  RuntimeError)`——InvalidURL 与已关闭连接池的 RuntimeError 都不在 HTTPError 体系内，
  新 provider 站点必须沿用（api_providers × 2、graph/providers × 1）。
- `base_url_host` 定居 `siku/retrieve/providers.py`（畸形 URL 回退空串），勿移回
  `model_supply`（循环导入：model_supply → retrieve 包 `__init__` → indexer）。
- 换 embedding 模型必须全量重建：设置中心只返回中文告警不自动重建，重建出口在
  `add-desktop-library`（未 apply，先走 `siku index --rebuild`）。Ollama 无 rerank API。
- 冻结入口保留 `multiprocessing.freeze_support()`；mypy 按 pyproject 原样跑
  （`uv run mypy` 不带路径参数，传 `.` 会扫 `ui/src-tauri` 产物误报）。
- 端点错误体回显沿 HttpxLlmProvider 旧模式（BYOK 评审 P2）：settings/test 已按契约
  收紧「不回显上游错误体」，新代码勿扩散旧模式。

## 触发型（不主动做，全在 ROADMAP 台账有账）

Phase 6 签名与自动更新（等发布解禁决策）；Windows/Linux 实机冒烟（等发布解禁，清单
见 docs/desktop.md）；双通道基线补录（等 Ollama/云端 key 环境，路径见
benchmarks/README.md）；设置中心 Tauri 壳内真实端点手工冒烟（等真实 BYOK 环境）。
