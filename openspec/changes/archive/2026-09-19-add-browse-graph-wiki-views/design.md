# 设计：浏览/图谱/wiki 三个只读知识视图

本文记录约束冻结决议（tasks.md「约束冻结」三项）与实现落点。apply 阶段如与本文冲突，
以本文为准修订实现，反之发现本文错误也应回改本文——两者不得静默漂移。

## 约束冻结决议 #1：三个只读 API 契约

全部端点为 GET 只读；错误体统一既有 `{code, message}` 中文口径。图谱/wiki 派生物
缺失属读取 404（资源尚不存在），复用映射表里仍适用的领域错误（如 parquet 损坏
`graph_store_corrupt` 409）。

### 浏览（笔记投影）

**清单 `GET /api/notes?page=1&page_size=20`** → `{notes, total, page, page_size}`：

- `notes[]` 字段：`source_id / source_name / note_path / source_hash / extractor`，
  全部派生自投影 frontmatter（复用 `notes_reader.scan_note_frontmatters`）。
- 稳定排序 = `note_path` 字典序（扫描函数既有口径，分页跨请求可复现）。
- `page` ≥ 1；`page_size` ∈ [1, 100] 缺省 20，越界参数走 FastAPI 校验 422
  `invalid_request`；`page` 超过总页数返回空 `notes`（合法空页，非 404）。

**单篇 `GET /api/notes/{source_id}`** →

```json
{
  "source_id": "…", "source_name": "…", "note_path": "notes/<同名>.md",
  "source_hash": "…", "extractor": "…",
  "anchors": ["背景", "方案"],
  "content": "# 标题\n\n## 背景\n…"
}
```

- `content` = 投影全文剥去 frontmatter（Markdown 原文，渲染交给前端）；
- `anchors` = 正文 `## <anchor>` 区块名按阅读顺序；单块投影为空数组（`content`
  内部锚点不虚构）；
- 按 `source_id` 查找 = 现扫全部投影 frontmatter 后匹配（桌面千级量级可接受，
  文件名与 source_id 的派生关系不作为查找依据，避免路径约定漂移即失效）；
- 不存在 → 404 `note_not_found`。

### 图谱

**统计 `GET /api/graph/stats`** → `{nodes, edges, communities, types}`：节点/边/
社区三个聚合数 + `{<实体类型>: 计数}` 分布（画布图例用）。与 POST `/api/graph`
（生成）同路径不同方法，无冲突。

**有界子图查询**（三个查询共用同一响应形状）：

```json
{
  "nodes":  [{"entity_id", "name", "type", "degree", "community_id"}],
  "edges":  [{"source", "target", "type"}],
  "truncated": false,
  "total_nodes": 0, "total_edges": 0
}
```

- `GET /api/graph/overview?limit=200`：节点 = 度数 top-N（并列按 entity_id 字典
  序）；边 = 两端均在节点集内的诱导边；`truncated` = 全图节点超上限；`total_*` =
  全图实体/边数。这是画布初始视图。
- `GET /api/graph/search?q=<必填非空>&limit=20`：按实体名大小写不敏感包含匹配；
  排序 = 度数降序后名称字典序；`truncated` = 命中候选超上限；`total_nodes` = 命中
  候选数；`total_edges` = 0（搜索不回边，选中后经邻域展开）。
- `GET /api/graph/neighbors/{entity_id}?limit=50&depth=1`：自中心 BFS；`depth`
  ∈ [1, 2]；节点数（含中心）≤ limit；同层内按度数降序、entity_id 字典序择优；
  边 = 选中集合的诱导边；`truncated` = 深度内候选超上限；`total_*` = 深度内候选
  全集的节点/诱导边数。实体不存在 → 404 `graph_entity_not_found`。
- 参数上限（服务端硬顶）：overview `limit ≤ 500`、search `limit ≤ 100`、
  neighbors `limit ≤ 200`、`depth ≤ 2`；超限 422 而非静默收紧。
- 响应 SHALL NOT 含存储文件路径；`community_id` 来自 parquet 社区表（单层划分，
  每实体恰属一个社区，画布着色与 wiki 条目一一对应）。
- 图谱未构建 → 404 `graph_missing`；parquet 损坏沿用既有 `graph_store_corrupt`
  409（复用 `map_domain_error`）。每次请求现读三件表（桌面单用户，读 parquet
  毫秒级；不引入失效协调，10⁵ 边复核信号由 ADR-0003 触发器管辖）。

### wiki

**清单 `GET /api/wiki/entries`** → `{entries: [{community_id, title, generated_at}]}`
**单条 `GET /api/wiki/entries/{community_id}`** → `{community_id, title, content,
generated_at}`：

- 内容只派生自 `data/wiki/entries/`（清单扫 `community-[0-9]{4}.md`，复用
  `entry_file_name` 生成单条路径）；`content` = 条目 Markdown 全文；`title` =
  条目首个非空 `# ` 标题，缺失回退 `社区 XXXX`。
- **时效元数据 `generated_at` = 条目文件 mtime（ISO 8601 本地时区）**：渲染器
  确定性无时间戳（wiki/render.py 明文约定），mtime 即生成时间的唯一事实，不改动
  产物格式。
- wiki 未生成 → 404 `wiki_missing`；条目不存在 → 404 `wiki_entry_not_found`。
- 读取路径不触碰 `wiki_generator`/`summarizer_factory`（读不触发写，spec 硬性
  要求），测试以注入失败的 generator 验证。

## 约束冻结决议 #2：画布数据形状与依赖钉定

- **裁剪分工：服务端是唯一权威**。前端不做任何整图拉取或客户端聚合，只渲染响应
  集合，`truncated=true` 时展示「已截断」横幅（附 total）。客户端不再二次裁剪，
  保证前端规模上限 = 服务端硬顶。
- **依赖钉定**（`ui/package.json`，实际版本由 package-lock 锁定）：
  - `sigma@^3.0.3`（WebGL 渲染器，ui/README 既定路线）
  - `graphology@^0.26.0`（图数据结构）
  - `graphology-layout-forceatlas2@^0.10.1`（初始布局；有界子图 ≤ 500 节点，
    同步 `assign` 若干十次迭代即可，不引入 worker 复杂度）
  - Markdown 安全渲染：`marked@^18` + `dompurify@^3.4`。两者为防注入的标准件
    （DOMPurify 是浏览器端 sanitize 事实标准），非 Non-goals 所指「重依赖」；
    封装为 `ui/src/markdown.ts` 单一入口：`renderMarkdown(text)` 内部先 marked
    解析再 DOMPurify 清洗，全应用唯一渲染点。
  - 不引入 @react-sigma 封装层：Sigma 实例在 `GraphView` 的 `useEffect` + ref 中
    直接装配、卸载时 `kill()`，少一层 reconciler 依赖。
- 节点着色 = 社区调色板（community_id 对固定 12 色 palette 取模）；悬停/选中
  走 Sigma 状态；节点点击打开侧栏实体卡（名称、类型、度数、「在问答中查询」、
  「展开邻域」）。
- 画布容器固定高度（视口自适应，窄窗口降高），空态（图谱未构建）与截断态均有
  非画布 DOM 提示，键盘可达性不依赖 WebGL 区域。

## 约束冻结决议 #3：实体→问答联动与 wiki 时效标注

- **联动形态：预填不发送**。图谱视图实体卡按钮「在问答中查询」→ App 级回调
  `onAskEntity(name)`：切换到问答视图并把问题框预填为 `请介绍「{name}」。`，
  焦点移入问题框，不自动提交（spec 场景明文要求）。实现为 App 持有 `question`
  状态并向 GraphView 下发回调，无路由/全局 store 介入。
- **wiki 时效标注字段**：`generated_at`（决议 #1）单条与清单都携带；UI 在条目
  头部展示「生成于 <本地时间>」，并配固定提示「图谱更新后可在终端执行
  `siku wiki` 重新生成」——只提示可重建，不提供任何重建入口（Non-goals）。
- 浏览视图锚点信息展示口径：单篇头部元数据行展示 `source_name / note_path /
  extractor` + anchors 逐个 chip；`source_hash` 以短哈希（前 8 位）展示、完整值
  进 `title` 悬浮。

## 实现落点

- `src/siku/api/reading.py`（新）：全部只读读取的纯函数（notes 清单/单篇、图谱
  统计/overview/search/neighbors、wiki 清单/单条）+ 读取级领域错误
  （`NoteNotFoundError / GraphEntityNotFoundError / WikiMissingError /
  WikiEntryNotFoundError`；图谱派生物缺失复用既有 `GraphArtifactsMissingError`
  映射 404 `graph_missing`，wiki 条目文件读失败原样上抛走 500 口径）。
  BFS 与度数计算用 stdlib，输入为 `load_graph` 产物。
- `src/siku/api/models.py`：`NoteSummary / NotesPageResponse / NoteDetailResponse /
  GraphStatsResponse / GraphNodeResponse / GraphEdgeResponse / GraphSubgraphResponse /
  GraphSearchResponse / WikiEntrySummary / WikiEntriesResponse / WikiEntryDetailResponse`。
- `src/siku/api/app.py`：挂载 8 个 GET 端点，错误内联映射（settings 先例）；
  reading 函数不注入工厂（只读派生物，现读现算与 library 清单同口径）。
- 测试 `tests/test_api_reading.py`（契约先行）：notes 分页/排序/404；图谱统计/
  overview/search/neighbors 与截断；10⁴ 边 fixture（直接 `save_graph` 构造，
  不经 LLM）；wiki 读取不触发生成（注入必炸 generator）；OpenAPI 快照零漂移沿用
  既有测试。
- UI：`ui/src/BrowseView.tsx`、`ui/src/GraphView.tsx`、`ui/src/WikiView.tsx`、
  `ui/src/markdown.ts`（新）；`ui/src/api.ts` 类型与请求函数；`ui/src/App.tsx`
  导航扩为 问答/浏览/图谱/wiki/资料库/设置 六页 + `onAskEntity` 联动；
  `ui/src/styles.css` 增量样式（沿用既有设计令牌与窄窗口断点）。
- UI 测试：三视图各一（mock `./api` fetch 层；Sigma/graphology 以 `vi.mock`
  替身绕开 jsdom 无 WebGL，画布交互不进单测、进手工冒烟）。

## 已知取舍

- `GET /api/notes/{source_id}` 每请求全扫 frontmatter：桌面千级投影毫秒级，换取
  不依赖「文件名含 source_id」的路径约定。
- 图谱每请求现读 parquet：不做进程内缓存，避免与重建写路径的失效协调；量级
  复核信号归 ADR-0003，不在本 change 预先优化。
- `generated_at` 用文件 mtime：挂载盘/备份还原可能改变 mtime，但 wiki 产物本身
  不含时间戳，此为不破坏确定性渲染前提下的最优时效来源；展示口径按「派生物最近
  写入时间」理解。
- Sigma.js 不进 jsdom 单测：WebGL 上下文在 jsdom 不可得，画布装配以 vi.mock 替身
  保障组件逻辑可测，画布真实交互交给手工冒烟（交付门禁既有项）。
- wiki 条目文件名严格按 `community-[0-9]{4}.md` 识别：community_id ≥ 10⁴
  （`entry_file_name` 产生五位数文件名）不入清单；需万级社区才触发，现实遥远。
- notes 单篇读失败折叠为 422 `note_parse_error`（沿用 `notes_reader` 既有口径），
  与 wiki 条目读失败走 500 的口径不一致，留待后续统一读取面错误语义时收敛。
