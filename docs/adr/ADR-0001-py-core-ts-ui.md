# ADR-0001：双语言栈——Python 决策内核 + TypeScript 界面

- **状态**：已接受（通用 UI 组件库选择部分由 ADR-0011 取代）
- **日期**：2026-09-17

## 背景

图谱/RAG 管线的全部现成轮子——GraphRAG、LightRAG、graphify、Docling、sentence-transformers、本地 embedding——都在 Python 生态；owner 的既有能力栈是 Java（平台团队，阿里规范 + MyBatis），界面必然是 Web 技术。争议：要不要顺手用 Java 统一栈，或追新用 Go/Rust。

## 决策

**内核 Python 3.12+（uv + FastAPI + typer），UI TypeScript + React + Vite。**
Rust 只出现在两处——LanceDB 内部与 Tauri 壳——都不需要本项目写。

| 侧 | 语言 | 内容 |
|---|---|---|
| 内核 | Python | 摄取规范化、切块、embedding、图谱抽取与社区摘要、wiki 生成、检索与问答编排、localhost HTTP 服务 |
| 界面 | TypeScript | vault 浏览、Sigma.js 图视图、wiki 阅读、对话、设置 |

## 理由

1. 选型一切让核心能力复用最大化：抽取层重写（Java 化）等于数月白费换一个更差版本；
2. 阶段一本地安装体验由 uv 保证（秒级、自带解释器管理）；
3. UI 侧 React 生态（shadcn/ui、Sigma.js + graphology 路线）无替代必要。

## 被否选项

- **全 Java**：与"翻译税"同构——Python 原型的验证收益 ≠ Java 重写的上线收益，且抽取生态为零；
- **Go / 纯 Rust 内核**：AI 生态引力不在那边，抽取/embedding 全部要 FFI 回 Python，纯增摩擦；
- **Node 内核**：LlamaIndex.TS 等移植版永远比 Python 原版慢一拍、缺一块。

## 代价与风险

- UI/内核双栈，一人项目需维护两套工具链（CI 已按两栈配置）；
- 阶段二打包 Python sidecar（PyInstaller 路线）是已知的工程脏活，已排入阶段二而非现在。

## 复核信号

若未来内核 90% 以上代码时间在纯 IO 编排且 TS 生态出现同等能力的图谱/抽取一等实现 →
可评估收编；在此之前本 ADR 不重开。
