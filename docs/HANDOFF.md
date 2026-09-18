# HANDOFF — siku 交接文档

> **接驳点，非常驻知识库。** 常驻知识分属四层：宪法 `openspec/project.md`、协作规范
> `AGENTS.md`、路线 `docs/ROADMAP.md`、相关决策 `docs/adr/`。本文件每次交接整体重写，
> 只写接手者马上需要的状态。

- **更新时间**：2026-09-18
- **仓库**：`~/siku` → github.com/qiyangfan/siku（私有；SSH 推送，gh keyring 认证）

## 现状

- Phase 0–4 已完成归档。Phase 5（Tauri 桌面壳，`openspec/changes/add-tauri-desktop-shell/`）
  已在本分支 **feature/tauri-desktop-shell 实现完毕，全部变更未提交**（含 change 文档、
  内核、Rust 壳、CI/发布流），等待用户复核后提交合入 main。
- 交付物：`siku serve` 增 `--vault/--data-dir/--ui-dir/--watch-stdin`（旧默认值回归锁定）；
  `src/siku/sidecar.py` 冻结入口（freeze_support + 内置模型离线缓存）；
  `ui/src-tauri/` Tauri 2 壳（动态端口、健康检查、失败页、进程组回收、单实例）；
  `scripts/build_sidecar.py`（PyInstaller onedir + bge-m3/reranker 内置，产物 7.3GiB，
  不入库）；`.github/workflows/release.yml`（tag→四 target→Release→Cask，失败不发布）；
  CI 增 Rust fmt/clippy/test 作业；文档 `docs/desktop.md`。
- 桌面决策已冻结于 design.md「约束冻结决议」：平台矩阵、tap=qiyangfan/homebrew-tap、
  数据目录=`应用数据目录/siku/{vault,data}` 零迁移、sidecar onedir + 离线权重。
- macOS arm64 安装后全链路冒烟已通过（fake LLM：健康→同源 UI→带引用问答→退出回收
  零孤儿）；**Windows/Linux 冒烟未做**。

## 验证

- `uv run pytest`：439 passed；ruff/format/mypy/pre-commit 全绿；openspec changes+specs
  strict 1/1 + 5/5；golden set 回归门禁通过；OpenAPI 快照零漂移。
- `cargo test/clippy/rustfmt`：3 tests 通过、零告警；`ui npm lint/test/build` 通过。
- `npx tauri build` 实际产出 siku.app + 4.1GB DMG；release.yml/cask 生成器仅过本地校验，
  **未经真实 runner 验证**。

## 下一步（唯一排序）

1. 用户复核本分支 → 提交合入 main → 打 tag `v0.1.0` 触发 release.yml 首跑。
2. Release 产物在 Windows/Linux 实机冒烟（清单见 docs/desktop.md），回填
   review.md/desktop.md 后归档 change、同步主 spec、ROADMAP 勾稽。
3. 一次性仓库外动作：创建公开空仓库 `qiyangfan/homebrew-tap`，配 secret
   `HOMEBREW_TAP_TOKEN`（缺省时 Cask 步骤自动跳过）。

## 已知坑

- 冻结 Python 应用必须入口首行 `multiprocessing.freeze_support()`，否则 torch spawn
  子进程会重放整个 CLI（曾表现为 `No such option: -B`）。
- sidecar 冷启动 2–24s（解压+模型加载），健康超时已设 60s，勿调小。
- LanceDB 0.38 新连接 `list_tables()` 竞态：向量表探测必须 `open_table()`。
- 换 LLM 通道必须同步 graph/wiki 模型身份；muniu 租户必须关语义缓存。
- Tauri 壳不得把业务迁入 Rust；sidecar 必须显式绝对路径；Phase 5 产物 unsigned，
  签名/自动更新属 Phase 6，不得把"能打包"说成"受信任安装"。
