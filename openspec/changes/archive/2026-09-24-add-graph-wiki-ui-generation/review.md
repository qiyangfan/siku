# Review：图谱与 wiki 生成入口界面化

> 独立复核记录。结论：**通过**。门禁全绿 + DashScope 真实端到端冒烟（GUI 黑盒
> 点击）通过；一个浏览器运行时异常（与被测应用无关）已如实记录。

## 门禁证据（2026-09-24）

| 门禁 | 结果 |
|---|---|
| vitest | 68 passed（首轮 60 + 评审循环净增 8：GraphView +3、WikiView +5；另 3 例断言改造为按钮化路径） |
| eslint / tsc -b / vite build | 全绿（chunk >500kB 告警为既有） |
| pytest | 642 passed（Python 侧零改动，回归确认） |
| ruff check / format | 通过（`warning: No Python files found` 为 mypy 对 ui/ 的无关输出） |
| mypy | Success: no issues found in 106 source files |
| pre-commit --all-files | 全部 Passed |
| OpenAPI 快照 | 无变更（本 change 无契约改动），契约快照测试随 pytest 通过 |

## 设计决议落点复核

- **红线 1（UI ↔ 内核只经 HTTP）**：`buildGraph()`/`generateWiki()` 仅封装既有
  `POST /api/graph`、`POST /api/wiki`，请求体 `{}`；无业务逻辑进前端
  （ui/src/api.ts 增量即可证）。
- **决议 #2（不做就绪门控）**：两视图无 `ask_readiness` 依赖，未配置 key 时点击
  后由后端错误映射兜底——冒烟中 `notes_dir_missing`（422）的中文 message 在视图
  内 alert 展示、按钮恢复，即该路径的实机证据。
- **决议 #3（两段式）**：`graph_artifacts_missing`（409）经
  `isGraphMissingCode` 切换空态为构建引导；端点侧实机验证 `409 +
  graph_artifacts_missing`（curl），UI 分支由 vitest「生成遇图谱缺失时就地引导
  构建，构建成功后自动续跑生成」覆盖（断言 `wikiCalls === 2` 证明自动续跑）。
- **决议 #4（幂等路径）**：真实冒烟中「更新图谱」与「重新生成 wiki」均以
  `LLM 调用 0 次` 完成——未变语料全缓存命中，等价 CLI 默认行为。
- **决议 #5（长任务反馈）**：冒烟捕捉到「构建中…（可能需要几分钟）」禁用态
  截图；竞态沿用各视图独立序号（`buildSeqRef`/`generateSeqRef`），模式与既有
  load/search/expand 序号一致。

## DashScope 真实冒烟（owner 指定 DASHSCOPE_API_KEY，qwen-plus）

环境准备：tmp 语料 3 篇标准投影笔记（vault/notes/），`SIKU_LLM_*` env 层注入，
`serve --with-ui` + 内网浏览器黑盒点击。语料首放错误（裸 md 置于 vault/ 根）被
UI 失败反馈如实暴露——该轮验证点作废重置，属环境准备问题而非功能缺陷。

| 测试点 | 结果 | 证据（截图/日志） |
|---|---|---|
| 图谱空态：构建按钮 + 说明文案 | ✅ | 空态截图（构建按钮居中、无终端导向文案） |
| 构建中禁用态瞬态 | ✅ | 「构建中…（可能需要几分钟）」截图 |
| 真实构建 → 画布自动加载 | ✅ | 35 实体/31 关系/9 社区；结果行「LLM 调用 6 次」；Sigma.js 画布渲染 |
| 失败反馈：后端中文 message + 按钮恢复 | ✅ | `notes_dir_missing` 文案 alert 截图 |
| 已建态「更新图谱」幂等 | ✅ | 秒回，「LLM 调用 0 次」 |
| wiki 空态「生成 wiki」 | ✅ | 生成中禁用态 → 9 条目清单（LLM 调用 9 次） |
| 条目阅读 + 按钮化时效提示 | ✅ | 社区 0000 正文渲染，时效行改为「可点击重新生成 wiki」 |
| 「重新生成 wiki」幂等 + 旧选中清空 | ✅ | 「LLM 调用 0 次」，清单时间戳刷新，阅读面板复位占位 |
| 图谱缺失错误契约（无图谱 data dir） | ✅ | curl `POST /api/wiki` → 409 `graph_artifacts_missing` |

截图留存于 ZCode 会话 artifacts 目录（工具返回的 `*-tool-result-*.png`）。

## 未覆盖 / 诚实声明

- **GUI 层未点击**：两段式引导的界面切换、`empty_corpus` 反馈——两者为纯前端
  分支，由 vitest 用例覆盖；GUI 点击通道在冒烟后半段失灵（对照实验：hover 有效、
  任意按钮 click 均无效，重建标签页与 reload 均不恢复），判定为浏览器运行时
  异常而非应用缺陷——同一构建在异常发生前全流程点击正常。
- 冒烟首轮的环境准备失误（语料布局错误）已重置重跑，未污染任何验证点结论。

## 评审循环追记（归档后第二轮独立复核 + 修复，2026-09-24）

主对话全覆盖评审 + 独立子代理交叉复核共确认 3 个真实缺陷 + 1 个覆盖缺口，全部
修复并复跑门禁（vitest 68 / eslint / tsc / build / pytest 642 全绿）：

1. **empty_corpus 早退不刷新（P2，违反决议 #5「完成即刷新对应数据面」）**：内核
   `build_graph` 对空语料也无条件 `save_graph` 落空产物、读取面对空产物返回 200
   零值，原实现在 empty_corpus 时早退不调 loadGraph——已建态「更新图谱」遇语料
   清空时磁盘已重置为空而界面残留旧画布。修复：照常刷新 + 措辞改为「语料为空：
   图谱为空、无可展示内容」（GraphView）。
2. **已建态生成遇图谱缺失静默失败（P2，违反 delta「生成失败反馈 SHALL 展示
   message」）**：`graphMissingKnown` 只驱动空态卡切换，已建态「重新生成 wiki」
   遇 409 时无任何可见反馈。修复：已建态显式渲染引导 alert（指向图谱视图构建）；
   并将旗标清除提到 `empty_graph` 判定之前——200 即证明产物存在，防两段式
   「构建成功但零社区」场景残留过期引导（子代理发现）。
3. **生成成功后刷新失败无落点（P2，子代理发现）**：loadGraph/loadListing 内部
   吞错只 set loadError，空态卡与已建态（数据保留时）均不渲染——空态下成功 note
   与「尚未构建/尚未生成」标题同屏矛盾、已建态静默陈旧。修复：两视图空态卡补
   loadError 行 + 重试读取按钮，已建态补「刷新失败」告警卡（画布/清单保留）。
4. **两段式自动续跑期间按钮文案（P3）**：构建完成后自动生成 wiki 期间按钮仍显示
   「构建图谱」。修复：按 buildingGraph/generating 分档显示。

**记录不改码的设计边界（P3）**：跨挂载重复提交窗口——分钟级构建中切换视图卸载
组件后再切回，per-mount 序号与禁用态归零，理论上可重复并发 POST。后果被逐 chunk
抽取缓存与产物 last-write-wins 摊薄（幂等重建语义内）；模块级在飞旗标方案在现
「视图条件挂载」架构下会引入「卡死禁用」的更差缺陷，判定为冻结设计（决议 #5 的
视图内反馈口径）的已知边界，不在本 change 修码。

## 发现的既有问题（非本 change 引入，记录待立项）

1. `notes_dir_missing` 等生成路径错误文案仍为 CLI 导向（「请先执行 siku
   ingest」）——与 HANDOFF 已上报的 401 误报分型同类：HTTP 面文案与 CLI 共享
   同一映射（spec 既有要求），UI 导向化需在 messages 层分面处理，宜与凭证
   误报分型一并立项。
