# HANDOFF — siku 当前交接点

> 本文件只记录接手者马上需要的状态；常驻规则、架构与排序分别见 `AGENTS.md`、
> `docs/architecture.md`、`docs/adr/`、`openspec/project.md` 和 `docs/ROADMAP.md`。

- **更新时间**：2026-09-26
- **仓库/分支**：`~/siku` / `feature/adopt-mantine-ui-components`（第十六批评改 +
  第十七轮 UI 风格统一已分笔提交并推送）

## 本批完成（两个 change 归档入库 + UI 风格统一）

- `2026-09-26-refine-model-config-and-library-ux`：LLM 通道 DASHSCOPE_API_KEY
  环境变量回退（三层全空才回退、key 与通义兼容端点绑定、embedding/rerank 不回退）；
  settings 响应新增 `llm_env_fallback`；厂商预设 + 回退提示；导入投放区；
  「清理失效文档」危险配色；wiki/图谱空态就绪提示（不门控）；移动端底部五视图导航。
- `2026-09-26-add-llm-protocol-adapters`（ADR-0012）：LLM 通道第 5 字段
  `protocol`（openai-chat 缺省 / anthropic / openai-responses），三层合并 +
  CLI `--llm-protocol`；探测按表单协议；手改 config 越界 protocol 返回中文指引
  （GET 503 / PUT 前置拦截），ask_readiness 对 embedding protocol 同源拦截；
  ProtocolConfigError 结构化 kind 分型（kind 走 args 位置参，保 pickle/copy 圆厂）。
- 第十七轮 UI 风格统一（无 change，owner 直派）：theme 以 siku muted 三阶 ramp
  顶替 Mantine 默认 green/yellow/red（阶位 1=wash/2=描边/6=核心/7=加深/9=浅底文字，
  锚点值与原 token 逐字一致=视觉零漂移），CSS 语义 token 改由 ramp 派生，颜色双体系
  收口；gray 中性豁免（注释留痕）。进行中态去 `color="blue"` 回退主色；问答两卡
  圆角 lg→md、设置根 gap 拉齐；design-system 门禁扩展（静态启动页纳入间距/字号
  扫描，新增语义色同源 + 浅底对比度 ≥4.5 守卫）；GraphCanvas 边色常量化；
  折叠开关 ▾ 字符改 IconChevronDown（裸渲染环境字形伪影）。

## 验证与限制

- pytest 681 全绿；vitest 106 全绿；ruff / eslint / vite build 全绿；
  `openspec validate --specs --strict` 8/8；OpenAPI 快照已随契约再生成。
- UI 实机走查（IAB + preview 驾驶舱）六视图配色统一 pass；1280/375/320 无横向
  溢出（第十六轮已验）；桌面/移动安装包未重新冒烟。
- 评审循环：第十六批两轮独立复核收口（见归档件 review.md）；第十七轮经独立子代理
  复核 + 评审迭代循环两轮收敛。

## 已知边界与下一步

- 桌面 GUI 进程读不到 shell 环境变量：回退只在终端 serve 场景生效；桌面侧用
  设置中心预设 + 直填 key。sidecar 环境注入未做（Non-goal，需要时另立 change）。
- 上报待立项（第十六批评审确认，见归档件 review.md）：401/403 凭证被拒被误导为
  「补全 base_url/model」需分型；config.toml 损坏引导死路；CLI 传参时
  ask_readiness 偏保守；生成路径错误文案 CLI 导向，宜与分型同批做双面文案。
- 「siku 走查发现 2026-09」清单：ink-faint 对比度项已销，余项仍待修。
- 本机残留旧 serve 进程（桌面 :51194、演示 :8123）跑旧构建，验证需重启；
  /tmp/siku-ui-check/ 验收截图可删。
- ROADMAP 队列为空；开新 change 前先按 `docs/ROADMAP.md` 对齐排序。
