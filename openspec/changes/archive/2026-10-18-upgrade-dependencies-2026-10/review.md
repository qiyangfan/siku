# 评审记录：upgrade-dependencies-2026-10

- 执行轮次：2026-10-18（apply 全程单轮，逐批验证）
- 结论：**21 项任务全部完成**，其中 1 项带备注（typer 受 docling-core 上界钉住）、
  1 项带替代验证路径（图谱视觉回归经一次性 harness）。归档与 ROADMAP 回写待评审接受。

## 各批次终态与证据

| 批次 | 终态 | 证据 |
|---|---|---|
| A：Python lock 刷新 | ✅ | `uv lock --upgrade`（filelock 临时钉 `<4`，批次 C 解除）；全量 pytest **862 passed, 1 skipped**（与 HANDOFF 基线一致）；pydantic-settings 2.16 / lancedb 0.40 / pyarrow 26 / fastapi 0.143.5 一把过 |
| B：ruff 0.17 + mypy 2.4 | ✅ | ruff check + format **零 diff**（预期的 F406/format churn 未出现）；mypy 2.3.1 与 2.4.0 全量输出**逐字节一致**（唯一报错为既有 `tests/document_fixtures.py` 模块解析错误，升级前即存在、零新增；HANDOFF 已注明 mypy 非门禁） |
| C：filelock 4 | ✅ | filelock 3.32.7 → **4.2.2**；锁相关 5 个测试文件 **72 passed**；双进程冒烟：A 进程跨进程持锁 4s、B 进程恰在 2.00s 抛 `LibraryWriteBusyError`、A 正常释放——fcntl 协议与"锁文件不删"语义保持 |
| D：前端 minor/安全批 | ✅ | react 19.3.1 / @mantine 9.7.3 / marked 18.1.1（ReDoS 修复）/ dompurify 3.4.17 / tabler 3.49 / vitest 5.0.5 / jsdom 30.1.3 / jest-dom 7.0.1 / tauri-cli 2.12.3；lint/test/build 三绿，vitest **133**（与基线一致） |
| E：eslint 10 全家桶 | ✅（带处置） | eslint 10.13.0 + @eslint/js 10 + typescript-eslint 8.71.2 + react-hooks 7.1.1 + react-refresh 0.5.7 + globals 17；新规则 13 个报错 triage：**真违规 3 处已修**（`GraphCanvas.tsx` 渲染期写 ref ×2 → 移入 effect；先使用后声明 → `applySelection` 前移；`api.ts` 死赋值删除），**`set-state-in-effect` 10 处降 warn**（六个视图取数模式级 React 债务，独立重构面，理由写进 eslint.config.js 注释）；lint 0 error / 9 warning |
| F：vite 8 + plugin-react 6 | ✅ | vite 8.3.4 + @vitejs/plugin-react 6.1.2；Rolldown 生效（构建提示切至 rolldownOptions，构建 3.5s → **0.8s**）；config 仅 plugins/proxy/test 三项，无静默失效面 |
| G：TypeScript 6.0.2 | ✅ | `~5.9.2` → `~6.0.2`；TS2882 三处 CSS 副作用 import 报错（`noUncheckedSideEffectImports` 新默认）→ `vite-env.d.ts` 补 `declare module "*.css"`；`tsc -b` 全绿 |
| H：sigma 4 + 视觉回归 | ✅ | sigma 4.0.3；`GraphCanvas.tsx` 适配：选项拆 `{settings, styles}`、`labelColor`/`labelSize` 迁入样式层（labelColor 绑定节点属性，主题切换写属性替代 v3 `setSettings`）、删 `defaultEdgeType`、`itemSizesReference` 显式钉 `"screen"` 保持 v3 观感；源码确认 styles 传入即整体替换，故 `...DEFAULT_STYLES.nodes` 扩展。视觉回归：vault 为空（图谱抽取需 BYOK 端点，无法造真实产物）→ 一次性 harness（夹具 14 节点 3 社区驱动真实 sigma 4 渲染管线）截图亮/暗主题 + 点击选中放大 + 相机动画 + 主题切换重着色，全部符合 v3 行为；**harness 已删除** |
| I：Rust | ✅ | tauri 2.12.4 / tauri-build 2.7.3 / single-instance 2.5.4 / wry 0.57.0 / tao 0.37.1；ureq 3.4.2（`Agent::config_builder().timeout_global()` + `into_body().read_to_string()`，两处重复构造收敛为 `health_check_agent()`）；edition 2021→2024（`cargo fix --edition` 零机械改动；唯一 drop-order 信号经人工评估语义安全）；MSRV 1.77→**1.90**（tauri 2.12.x 要求，见决策 #3）；fmt/clippy -D warnings/test **11 passed**（含孤儿进程组回收） |
| J：CI + hooks | ✅ | setup-uv v10.2.0→v10.3.0（ci.yml 两处 + release.yml 一处）；pre-commit-hooks v5→v6.0.0（被移除 hook id 未使用）；ruff-pre-commit rev 对齐 v0.17.1；`pre-commit run --all-files` **8/8 Passed** |
| 收尾 | ✅ | sidecar 产物门禁：真实构建 **641 MiB**、pandoc 3.11 SHA-256 校验随包、`check_sidecar_artifacts.py --probe` 实跑通过（filelock 4 / lancedb 0.40 / pyarrow 26 进包工作），三平台完整门禁留 CI；检索链路零改动（`git status src/siku/retrieve src/siku/graph` 空）→ golden set 免跑；最终全量 pytest **862**、vitest **133**、openspec strict **1 passed** |

## 评审决策记录

1. **typer 留 0.26.8**：docling_core 2.102.0 上界 `typer<0.27.0` 压制（docling 为
   ingest-pdf extra）。抬 typer 会让 extra 无法解析；0.27 的增量仅 help 外观。待
   docling-core 放开后随下轮带入。
2. **`set-state-in-effect` 降 warn**：react-hooks 7 compiler 诊断新规则，命中的 10 处
   均为既有取数模式（App/Browse/Graph/Library/Wiki 视图 + App 建议列表/焦点命令
   effect），正确修法是渲染期派生/事件驱动的行为重构，不该在依赖升级件内吞 UI 回归
   风险。清零后应恢复 error（已写入 eslint.config.js 注释）。
3. **MSRV 1.77→1.90**：tauri 2.12.x 要求 Rust 1.90；2.12.3 含 NSIS 安装器降级修复
   （Windows 发布面真实收益）。本机与 CI 均为 stable 1.99，发布走预构建产物。
4. **Rust 工具链漂移修复**：本机 clippy/rustfmt（1.99.1）比 CI 上次绿时新，出现一处
   `map_or(true,…)`→`is_none_or`（clippy 新 lint）与一处 import 排序口径变化，均为
   机械修复，无行为变化。CI 下轮跑 stable 会收敛到同一状态。

## 上游观察项（不阻塞，供后续跟进）

- sigma 4 渲染期反复输出 WebGL warning：`GL_INVALID_OPERATION: glDrawArraysInstanced:
  Active draw buffers with missing fragment shader outputs`（相机动画帧期间；渲染结果
  正确、无 error）。疑为上游着色器管线问题，可考虑向上游报 issue。
- lancedb 0.40 官方未在 pyarrow 26 跑 CI（约束满足）；本轮全量向量相关测试绿，风险
  观察即可。

## 归档前待办（留归档步骤）

- 向 `docs/ROADMAP.md` 触发器台账写入三条：① typescript-eslint 宣布支持 TS 7 → 另开
  TS 7 升级件；② Node 26 进 LTS（2026-10-28 已过）→ 例行维护顺手切 CI Node；③
  LanceDB 原生 FTS 重评（上游 #4516/#4364 关闭且 golden set A/B 不降 → 另开迁移件）。
- 本轮搁置的历史阻塞项（非本件范围，维持原状）：多平台实机安装冒烟（发布解禁触发）、
  Phase 6 签名/自动更新（owner 双条件裁决）、本地 Ollama 通道基线（待在线环境）。

## 验证环境边界

- 本机 macOS arm64（sidecar 门禁仅本机平台；Windows/Linux 归 CI）。
- DASHSCOPE_API_KEY 假红口径：全量 pytest 均按 HANDOFF 口径 `env -u` 执行。
- 图谱视觉回归为夹具 harness 替代路径（vault 空且无模型端点），真实语料下的渲染
  抽查建议随下一次实机冒烟顺带执行。
