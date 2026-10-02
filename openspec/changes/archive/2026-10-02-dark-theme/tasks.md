# 实施任务

每项 ≤ 2h；对比度类守卫先红后绿。验证证据见 review.md。

## 1. 守卫先行（先红）

- [x] 1.1 `design-system.test.ts` 补暗底断言：ink/ink-soft/ink-faint/accent/success/warning/danger 对暗 canvas 与暗 surface 均 ≥4.5:1（值先按 design.md D3 标定表写入）。
- [x] 1.2 同文件补 wash 断言：warning/danger/accent 的暗 wash 上文字（ramp 3/4 阶，红族钉 3 阶）≥4.5:1；红族 4 阶不达标这条差异用断言钉住，不通吃阶位。
- [x] 1.3 补切换入口组件测试：初始跟随系统（mock `matchMedia` 暗偏好 → 暗态渲染）、点击后手动值优先且持久化、入口标签随目标态反转；`test-utils` 提供 light/dark 两个包裹入口。
- [x] 1.4 红灯实证：resolver `dark` 仍为空时 1.1/1.2 必红（记录报错），再进入实现。

## 2. 取值与分流

- [x] 2.1 按 design.md D2/D3 表把方案相关 token 从 `variables` 分流进 `light` 块（现值逐字节平移，顺带核对 `variables` 里无残留方案相关 token）。
- [x] 2.2 `dark` 块落 D3 标定值（含 mantine body/text 与 shadow-card）；注释登记「第二个 canvas 例外」位（D4）。
- [x] 2.3 边线色改取值函数（亮 `rgba(ink,0.18)` / 暗 `rgba(#e6ecf3,0.18)`），`GraphCanvas` 按解析后主题取值。
- [x] 2.4 全仓 grep 复核：页面/组件无裸色值（`#[0-9a-f]{3,6}` 直写、`rgba(` 直写仅存 theme.ts 与 canvas 例外两处）。

## 3. 接线与入口

- [x] 3.1 `main.tsx` 去三处 `forceColorScheme="light"` 改默认跟随系统；`preview.tsx`/`test-utils.tsx` 的 light 固定保留（预览/测试确定性基线），test-utils 另挂 dark 入口。
- [x] 3.2 两处 HTML（`ui/index.html`、`ui/src-tauri/shell-ui/index.html`）接入主题初始化脚本（防首帧闪烁）。
- [x] 3.3 壳静态启动页补 `prefers-color-scheme` 暗色媒体块（token 与主应用同源同值）与 `color-scheme: light dark`；`meta theme-color` 两态各一。
- [x] 3.4 header 操作区加主题切换入口（图标按钮 + aria-label 目标态），复用既有 Mantine 组件，不手搓按钮。

## 4. 验证与收尾

- [x] 4.1 `uv run pytest`、ruff check/format 全绿；UI `tsc + eslint + vitest run + vite build` 全绿（含 1.1–1.3 守卫）。
- [x] 4.2 手工冒烟：375/768/1280 × 亮暗两态走查（暗态本轮为真验项，非 N/A）；系统偏好切换→刷新→手动覆盖→清除手动值回系统，四级路径各截帧。
- [x] 4.3 完成独立代码审查（含对比度达标取证与「无第三套主题机制」核对）。
- [x] 4.4 主规格 sync 进 `web-ui` 后归档；ROADMAP/HANDOFF 更新（含 Phase 6 终态裁决行，见仓库 HANDOFF）。
