# Review：浏览/图谱/wiki 三个只读知识视图

## 红线与 spec 符合性

- **红线 2（UI↔内核只经 HTTP）**：三视图全部数据经本 change 新增的 8 个 GET 端点
  （notes 清单/单篇、graph stats/overview/search/neighbors、wiki 清单/单条）；
  UI 无任何直连 vault/SQLite/LanceDB/parquet 的路径（三个视图组件仅调 api.ts 的
  fetch 封装）。`/api/graph/*` 响应不含任何存储文件路径（spec 硬性要求）。
- **红线 3（只读边界即语料保护）**：读取路径不触碰 `wiki_generator`/
  `summarizer_factory`/任何写盘函数；reading.py 模块级口径「纯派生查询，绝不写回」。
  实证：单测 `test_read_never_triggers_generation` 注入必炸 generator 断言读取不
  触发生成；冒烟中以文件级 `mtime+size` 快照比对 11 次端点请求（含 404 路径），
  vault/data **零变化**。
- **大图上限与截断（ADR-0003 量级防线）**：服务端硬顶 overview ≤500 / search
  ≤100 / neighbors ≤200（depth ≤2），超限 422 而非静默收紧；邻域候选超限按层序
  优先、层内度数降序 → entity_id 字典序择优（直连邻居优先于远层高度数节点），
  响应携带 `truncated` + `total_nodes/total_edges` 明示。
  10⁴ 边 fixture（100 核心环 × 95 叶）实测 overview limit=200 恰返回 200 节点、
  truncated=true、total 计数正确；前端只渲染响应集合并展示「已截断」横幅，
  不做整图拉取或客户端聚合。
- **渲染防注入**：Markdown 渲染唯一入口 `ui/src/markdown.ts`（marked 解析 →
  DOMPurify 清洗，禁 style/form/input/button 标签）。单测四剧本：常规结构、
  剥 `<script>`/`onerror`、剥 `javascript:` 链接、剥 iframe/style；BrowseView
  集成测试再以含注入 payload 的真实投影内容断言 DOM 无 script、img 无 onerror。
- **可访问性**：主要操作（清单条目、分页、搜索、展开、问答联动）全部为原生
  button/input，键盘可达；画布信息有 DOM 等价物（统计行、截断横幅、实体面板），
  `role="img"` + aria-label 描述画布；窄窗口（≤48rem）双栏降单栏、画布降高、
  面板转为流式布局。

## 约束冻结决议落点（详见 design.md）

- **决议 #1（API 契约）**：8 个 GET 端点 + 统一 `{nodes, edges, truncated,
  total_*}` 子图形状 + 404 语义（note_not_found / graph_missing /
  graph_entity_not_found / wiki_missing / wiki_entry_not_found），全部落既有
  404/422 状态类；parquet 损坏沿用既有 `graph_store_corrupt` 409。OpenAPI 快照
  经 `python -m siku.api.contract --refresh` 刷新，diff 纯增量 +702 行、既有端点
  零漂移（`test_openapi_snapshot_has_no_drift` 继续守卫）。
- **决议 #2（画布形状与依赖）**：sigma@^3.0.3 + graphology@^0.26.0 +
  graphology-layout-forceatlas2@^0.10.1（同步 assign，无 worker）；marked@^18 +
  dompurify@^3.4 为防注入标准件（Non-goals 所限为「重依赖」，两者 gzip 合计
  ~25KB，不属重前端依赖）；不引入 @react-sigma 封装。裁剪分工：服务端唯一权威，
  前端零二次裁剪。
- **决议 #3（联动与时效）**：实体→问答为预填不发送（`onAskEntity` 切问答视图、
  预填 `请介绍「{name}」。`、焦点入框）；wiki 时效字段 `generated_at` 取条目
  文件 mtime（渲染器确定性无时间戳，mtime 即生成时间唯一事实），UI 只提示可重建
  不提供入口。

## 测试证据

- pytest 全量 **577 passed**（基线 546 + 本 change 新增 31，含 10⁴ 边 fixture
  的上限与截断测试与评审循环回归测试）；ruff check/format、mypy（98 文件零错误）、
  pre-commit 全绿；openspec strict：specs 7/7。
- 前端 **vitest 43 passed**（markdown 6 + BrowseView 8 + GraphView 4 + WikiView 3
  + App 7 + Settings 8 + Library 7），eslint 零错误、`tsc -b && vite build` 全绿。
  Sigma/graphology 在 jsdom 以 vi.mock 替身呈现（jsdom 无 WebGL），画布真实交互
  由手工冒烟覆盖。
- OpenAPI 快照仅含本 change 显式新增的 8 个路径（diff 逐路径核对）。

## 手工冒烟记录（2026-09-19，serve --with-ui + 假 BYOK 端点 + 真实浏览器）

本机无真实模型端点，沿用归档件口径以 openai 兼容 mock（/embeddings 确定性向量 +
/chat/completions 按提示词分派抽取 JSON/摘要/回答）替代三通道；真实语料 3 篇
Markdown → ingest 3 created → index 9 chunks → graph（4 实体/4 边/2 社区）→
wiki 2 条目；`siku serve --with-ui` + 浏览器逐视图点击：

1. **导航骨架**：问答/浏览/图谱/wiki/资料库/设置 六页签切换正常，问答原有闭环
   不受影响（健康徽标常显）。
2. **浏览视图**：清单 3 条稳定排序、分页控件（第 1/1 页）；点击 architecture.md
   打开只读阅读——标题、note_path、抽取器、短哈希（title 悬浮完整哈希）、锚点
   chips（content/设计原则/存储三件套）、Markdown 渲染（标题/段落）齐备；无任何
   编辑入口。
3. **图谱视图**：统计行「全图 4 个实体、4 条关系，2 个社区（颜色区分）」；WebGL
   画布渲染 4 节点 4 边，两社区呈绿/蓝着色；搜索「四库」命中 1 实体，点击 chip
   与**画布坐标点选**均弹出实体面板（类型/度数 3/社区 #0）；「展开邻域」后按钮
   转「邻域已展开」；画布缩放（滚轮）正常。评审循环后搜索提示语义不变
   （「命中 N 个实体，显示前 M 个」，截断时附细化关键词提示）。
4. **实体→问答联动**：「在问答中查询」切换到问答视图、预填 `请介绍「四库」。`、
   焦点入框、**未自动发送**（提交按钮仍在，spec 场景逐字满足）。
5. **wiki 视图**：清单 2 条目带「生成于 <本地时间>」；阅读条目展示摘要/成员实体
   （含锚点回链 chunk/源哈希）/关键关系（证据+来源）；头部固定时效提示「图谱更新
   后可在终端执行 `siku wiki` 重新生成」，无重建入口。
6. **只读边界实证**：对 vault/data 做文件级 mtime+size 快照 → 连打 11 次读端点
   （含三类 404 负路径）→ 快照 diff 为空，零写回。

## 已知取舍与遗留

- `GET /api/notes/{source_id}` 与图谱读取均为每请求现扫/现读（桌面千级/毫秒级），
  不做进程内缓存——失效协调的复杂度留给 ADR-0003 的 10⁵ 边复核信号。
- `generated_at` 依赖文件 mtime：备份还原可能改变 mtime，展示口径为「派生物最近
  写入时间」（design.md 已记账）。
- 画布初始布局含随机初始化 + FA2 120 轮迭代：同数据两次挂载布局不同（不影响
  确定性产物，纯前端视觉层）。
- vite 构建提示 chunk >500KB（sigma 主贡献）：桌面本地加载场景无网络代价，不引
  入 code-split 复杂度。
- 触发型遗留（与 HANDOFF 台账一致）：设置中心与资料库/本 change 三视图在 Tauri
  壳内的界面级实机冒烟等真实 BYOK 环境；serve 级全链路已如上记账。

## 评审循环修复记录（2026-09-19，第 1 轮初审 → 修复）

三域并行独立评审（后端读取面 / 前端视图 / 契约文档一致性）共 25 条 finding，逐条
溯源核验后修复 16 项、剔除 4 项虚构或非缺陷（跨响应边方向反转重复绘制——同一边的
方向在 parquet 行中恒定，不可能随查询翻转；渲染期 latest-ref 写入——惯用法非缺陷；
anchors 不感知代码围栏——与既有 reader 同口径的一致性选择；DOMPurify FORBID_ATTR
target 冗余——无害双保险），其余为同项合并。修复清单：

- **邻域截断口径对齐决议**：实现由全局度数排序改为层序优先、层内择优（直连邻居
  优先于远层高度数节点），补跨层回归测试；review.md 截断口径描述同步回改（消除
  design/review 静默漂移）。
- **浏览视图合法空页**：区分「空库」（total=0，展示空态）与「空页」（浏览中数据
  缩减，保留翻页器 + 返回提示），消除翻页死路。
- **只读链接导航守卫**：`handleMarkdownClick` 统一拦截渲染产物内 `<a>` 的默认导航
  （href 保留供悬浮查看），桌面壳内点击不再跳离应用；补守卫单测。
- **wiki 读取面**：条目文件名正则收紧为 `community-[0-9]{4}.md`（与
  `entry_file_name` 逐字对齐，顺带消除 `\d` 匹配 Unicode 数字的清单/单条不一致）；
  空 `# ` 标题回退社区名；单条目读失败由误导性 404 `wiki_missing` 改为既有 500
  `internal_error` 口径（不新增错误码）。
- **api.ts 非 JSON 错误体**：解析失败回退稳定 `{http_error}` 文案，不再冒泡语法
  错误误导为「无法连接」。
- **图谱视图**：搜索截断数上屏（「命中 N 显示前 M」+ role=status）；失败重试改
  视图内重载（弃 `window.location.reload` 全页刷新）；搜索/展开加请求序号防竞态。
- **竞态与陈旧态**：Browse/Wiki 全部异步加载加请求序号守卫；详情失败清旧内容，
  错误卡不再与上一篇正文同屏。
- **联动预填清旧答案**：实体→问答预填时清空上一轮回答卡与状态。
- **GraphCanvas**：移除挂载期重复 rebuildData（消除双倍 FA2 迭代）。
- **测试与文档**：删除 App.test 空洞断言（防 /api/ask 误触发由 mock 内逐请求断言
  承担）；neighbors 顺序断言去命名巧合化；design.md「6 个端点」笔误回改为 8。

### 第 2 轮对抗性复审（2026-09-19）与修复

复审以对抗视角攻击第 1 轮修复增量，确认 12 项修复本体成立、多数已被测试钉住，
另发现 4 项真实问题并全部修复：

- **P1 孤立实体致 overview/search 500**：被提及但未进入任何关系的实体是合法产物
  （merge 入表全部提及实体、自环边丢弃），overview/search 排序键直索引度数表抛
  KeyError、画布初始加载整体不可用。修复为 `degrees.get(..., 0)` 兜底（与节点视图
  既有口径一致），补孤立实体回归测试。
- **P2 共享请求序号致 loading 旗标卡死**：搜索与展开、翻页与详情共用同一序号 ref
  时，被跨操作否决的一方 finally 条件不成立，loading 永久为真。修复为按操作拆分
  独立序号（load/search/expand、page/detail、listing/detail）。
- **P2 实体联动预填不防在途回答**：问答 A 加载中预填问题 B，A 迟到后仍会挂在 B 下。
  修复为 App 增加问答序号，askEntity 递增使在途响应作废。
- **P2 翻页失败零反馈**：listError 只在首屏错误卡渲染，翻页失败时旧页纹丝不动。
  修复为分页器旁渲染行内告警（旧页保留可读）。
- 文档勘误：design.md 正则措辞 `\d{4}` → `[0-9]{4}`、虚构错误类名按实现勘误、
  补两条已知取舍（万级社区边界、notes/wiki 读失败状态码口径差异）。
- 补钉住测试：搜索截断提示上屏、预填清旧回答卡（走图谱联动真实路径）、详情失败
  清旧内容、翻页失败行内可见。第 3 轮收敛复审判定收敛，唯一建议（在途回答作废
  半边的并发测试）已补齐（受控 Promise 驱动迟到响应，断言不上屏）。
