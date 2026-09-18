# HANDOFF — siku 交接文档

> **接驳点，非常驻知识库。** 常驻知识分属四层：宪法 `openspec/project.md`、协作规范
> `AGENTS.md`、路线 `docs/ROADMAP.md`、相关决策 `docs/adr/`。本文件每次交接整体重写，
> 只写接手者马上需要的状态。

- **更新时间**：2026-09-18
- **仓库**：`~/siku` → github.com/qiyangfan/siku（私有；SSH 推送，gh keyring 认证）

## 现状

- **产品形态已定调（用户拍板）**：本地服务 + 全模型 BYOK 优先（对标 opencode 模式）；
  「本地优先」重定义为「本地可用」（不依赖服务器部署），非"数据不出本机"；云端多租户
  SaaS 不做，商业化后以"托管模型通道"入场。**Release 无限期禁用**（产品完善到一定
  程度前不考虑发布）。
- Phase 5（Tauri 桌面壳）已实现并合入 main（`93d0340` + 修复 `1c07b8b`）：`siku serve`
  路径参数/watchdog、`src/siku/sidecar.py` 冻结入口、`ui/src-tauri/` Tauri 2 壳、
  `scripts/build_sidecar.py`、CI Rust 门禁作业、`docs/desktop.md`。macOS arm64 全链路
  冒烟通过；**Windows/Linux 冒烟挂起**（等 BYOK 瘦身后的新产物）。
- **GitHub Actions**：`Release` workflow 已 `disabled_manually`（tag 不再触发构建）；
  两次 Release 试跑已取消，累计消耗少量配额分钟；`CI` 正常（main 绿：Python 3.12/3.14
  + 前端 + Rust fmt/clippy/test）。远端 `v0.1.0` tag 遗留未删（无 Release 对象，惰性）。
- 下一个 change（待用户确认后立项）：**模型供给 BYOK 化**——`ApiEmbeddingProvider`/
  `ApiRerankerProvider`、桌面配置文件（`~/.config/siku/config.toml`，env 覆盖）、
  golden set 双通道裁决、sidecar 剔除 torch/bge（DMG 4.1GB→几百 MB）；本地 bge 降级为
  可选离线 Provider + 指向 Ollama/LM Studio 端点，不删代码、不进安装包。

## 验证

- `uv run pytest` 439 passed；ruff/format/mypy/pre-commit 全绿；openspec strict
  changes 1/1 + specs 5/5；golden set 基线（本地通道）Recall@5=1.000 / MRR@10=0.957。
- `cargo test/clippy/rustfmt` 3 tests 零告警；ui lint/test/build 绿。
- 两次 Release 试跑结论：Linux 腿死于 runner 磁盘（修复已提交：磁盘回收 + 模型硬链接
  复制）；CI 桌面壳作业资源占位与 3.14 测试竞态修复均已验证。

## 下一步（唯一排序）

1. 用户确认后立「模型供给 BYOK 化」change（proposal 含 ADR-0006 修订：本地模型从默认
   降为可选；双通道质量门禁设计）。
2. BYOK 落地后重切瘦身 sidecar → 那时再决定是否解禁 release.yml、打首个对外 tag。
3. 桌面产品完善优先级（供排序参考）：配置文件 > BYOK 模型通道 > 三平台冒烟 > 其余。

## 已知坑

- 冻结 Python 应用必须入口首行 `multiprocessing.freeze_support()`（否则 torch spawn
  子进程重放 CLI，表现为 `No such option: -B`）。
- PyInstaller 冻结二进制无法运行时加依赖：桌面包要么内置全部依赖，要么走外部端点。
- CI 桌面壳作业需 sidecar/UI 资源占位目录（tauri-build 校验 resources 路径存在）。
- LanceDB 0.38 新连接 `list_tables()` 竞态：向量表探测必须 `open_table()`。
- 换 embedding/LLM 模型必须同步身份并全量重建；muniu 租户必须关语义缓存。
- Tauri 壳不承载业务；sidecar 显式绝对路径 + `--watch-stdin`；Phase 6（签名/更新）
  未启动。
