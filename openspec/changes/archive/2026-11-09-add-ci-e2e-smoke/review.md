# 评审记录：add-ci-e2e-smoke

> 本文件当前为 **apply 阶段实现证据**（2026-11-09），独立评审尚未进行；
> 归档前须完成独立评审并在此追加评审结论。

## 实现证据（apply 阶段）

| 项 | 证据 |
|---|---|
| e2e 套件 | `pytest tests/e2e -m e2e`：2 passed（端点自检 + 五段编排），本机口径 `env -u DASHSCOPE_API_KEY uv run python -m pytest` |
| 确定性自检 | 五段编排连续 3 次全绿（21.9/23.8/30.2s，仅时长抖动，断言零抖动）；含审查轮修复后多次复跑全绿 |
| 审查轮加固（2026-11-09） | ① boot 竞态有界重试：早退换端口重试 ×3（端口选号与 serve 绑定间隔秒级启动空窗）；故障演练（注入 exit=9 早退）证实 3 连试 + 逐次日志累积，恢复后回绿。② 配置目录密封：HOME/XDG_CONFIG_HOME/APPDATA 指临时区，serve 子进程不再读宿主真实分层 config.toml。③ 段 5 断言改用完整 SEED_MARKER 常量（单源）。 |
| 全量门禁零感知 | `pytest` 默认排除：862 passed + 1 deselected（e2e 用例被 addopts 排除，既有收集不变） |
| 门禁自证（断线演练） | 打断 fake `/v1/embeddings` 路径 → e2e 精确红在段 2（作业 failed，error=模型端点调用失败）；恢复后回绿 |
| ruff | `check` + `format --check` 双绿 |
| CI 工作流 | actionlint 通过 + YAML 结构断言通过；SC2129 两处按 shellcheck 建议以分组重定向收敛（新增第三行触发，修复在触发行所在簇） |
| openspec | `openspec validate add-ci-e2e-smoke --changes --strict` 通过（skip_specs 声明生效） |

## 首周 flake 观察纪律与降级预案

- **blocking 即入的依据**：全罐头无网络无密钥，断言纯确定性；本机 6 连绿 + 断线演练
  证明「该红时红、该绿时绿」。
- **观察期**：合入后首周逐次检查 e2e job。任何一次非代码原因的 flake 立即记 issue，
  标注触发环境与日志。
- **降级预案**：一周内出现 ≥2 次原因不明 flake，或单次 flake 定位超过一天，则临时把
  e2e job 改为 `workflow_dispatch` 手动触发（保留 nightly 可选），修稳后回 blocking；
  处置决策追加到本文件。
- **红线**：不允许以放宽断言换取绿灯；断言松动 = 门禁失效。

## 待确认与既有问题（非本件引入，证据在案）

1. **CI 首跑未执行**：需推送远端触发，本轮未经授权不执行 git push。推送后按上面
   预案观察首跑与门控两面（改动 `src/` 触发、纯文档跳过）。
2. **既有失败**：`tests/test_sync_removal.py::test_two_process_mutex_via_subprocess`
   在 HEAD 上即红（暂存本件改动复跑归因确认），与本件无关。机理：测试时序余量仅
   ~1s（holder 持锁 3s − CLI 锁超时 2.0s），而本机当前 `import siku.cli` 耗时
   3.8–6.9s，CLI 子进程启动越过了余量，等到持锁进程退出后才拿到锁、倒在 vault 校验。
   建议另开小件修（拉长 holder 时限或按环境参数化余量），本件不越界顺手改。

## 归档前清单

- [x] 独立评审：owner 指示随 2026-11-09 当轮收口直接归档（归档目录
  `2026-11-09-add-ci-e2e-smoke`），未另行开独立评审轮；以本文件实现证据、断线演练
  自证与门禁复验（887 passed + e2e 2 passed + ruff 双清）为准。
- [ ] CI 首跑两面验证：随推送后首周观察纪律执行（见上方「首周 flake 观察纪律与
  降级预案」；推送触发首跑，观察改动 `src/` 触发 / 纯文档跳过两面）。
- [x] ROADMAP 勾稽数回写（2026-11-09 已完成）。
