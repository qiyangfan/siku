# 评审记录：2026-10-02-dark-theme

## 第 0 步：守卫先行（tasks 1.4 红灯实证）

守卫测试（design-system.test.ts 暗色断言 + 主题切换入口组件测试）先于实现提交并运行，
resolver `dark` 仍为空块、`ThemeToggle` 尚不存在时实测：

```
Test Files  2 failed (2)
Tests       4 failed | 6 passed (10)

FAIL design-system.test.ts > 暗 wash 上的文字 ≥4.5:1…
    AssertionError: expected undefined to be '#e29a99'
FAIL design-system.test.ts > 暗色边线保持 hairline 分隔语义…
    TypeError: Cannot read properties of undefined (reading 'replace')
FAIL design-system.test.ts > 方案相关 token 不留在两态共用 variables
    AssertionError: …
FAIL design-system.test.ts > 正文/辅助字/强调与语义核心色对暗 canvas 与暗 surface 均 ≥4.5:1
    TypeError: Cannot read properties of undefined (reading 'replace')
（theme-toggle.test.tsx 因 ./ThemeToggle 不存在文件级收集失败）
```

红灯与「dark 块空」的因果成立，随后进入实现转绿。

## 验证证据（tasks 4.1/4.2）

- 后端：`python -m pytest -o addopts=""` **802 passed**（`env -u DASHSCOPE_API_KEY`
  隔离本机假红变量）；`ruff check .` 全过、289 files already formatted。
- UI：`tsc -b` 0 错、`eslint .` 0 错、`vitest run` **126 passed / 11 文件**
  （较上批净增 12：design-system 守卫 8 + 主题切换入口 4）、`vite build` 成功
  （仅既有 chunk 体积提示）。
- 裸色值复核（tasks 2.4）：`ui/src` 下 theme.ts 之外 grep
  `#[0-9a-fA-F]{3,6}|rgba?\(` 零命中；壳静态页字面值为无组件库页面的既定同源拷贝。
- 手工冒烟（内嵌浏览器，真实验证暗态）：
  - 三视口 × 两态六帧全过：1280×800 / 768×900 / 375×720，暗态画布、卡面、警示
    wash、危险 wash、导航药丸、表单控件、移动端底部导航均正常，无布局漂移；
    另走查设置视图、资料库视图暗态（错误提示卡、重试按钮正常）。
  - 四级主题路径（宿主真实处于系统暗偏好，路径一为实测非模拟）：
    1. 首次访问跟随系统 → 首帧暗（`data-mantine-color-scheme=dark`）且
       localStorage 无手动值 ✅
    2. 刷新 → 仍暗、仍无手动值 ✅
    3. 手动切换亮色 → `mantine-color-scheme-value=light` 落库，刷新后仍亮 ✅
    4. 清除手动值 → 刷新后回系统暗、存储为空 ✅
  - 壳静态启动页（http.server 直服）：系统暗偏好下首帧即暗；写入手动亮色后
    刷新仍亮——壳页暗色块与库初始化脚本接线正常 ✅

## 独立代码评审（tasks 4.3）

独立子代理只读评审（自行计算 WCAG 对比度、对照 node_modules @mantine/core 9.6.3
源核对 ColorSchemeScript 产物、突变法验证守卫捕获力、复跑全部门禁），结论：

- **7 项必查全部合格，无 P0/P1 缺陷，放行归档**：
  1. 对比度取证：7 核心色对暗 canvas/surface 全部 ≥4.5:1（ink 15.29/13.48、
     ink-soft 8.55/7.53、ink-faint 6.20/5.46、accent 5.54/4.88、success 7.25/6.39、
     warning 10.03/8.84、danger 8.07/7.11）；wash 配对 warning 7.005、danger(red3)
     5.223、accent 4.597、accent-strong 6.994；red[4] 对暗 wash 3.841 <4.5——
     D3「红族钉 3 阶」的标定依据复核成立，与断言值逐一吻合（误差 <0.005）。
  2. 无第三套主题机制：provider 仅 `defaultColorScheme="auto"`、库默认存储键、
     无自造存储键/自写监听/自研 hook；两处 HTML 内联脚本与库 9.6.3
     ColorSchemeScript 产物**逐字一致**（独立渲染比对 + 防漂移守卫双重确认）。
  3. 取值分流：variables 35 个 token 全为度量/排印刻度；light 块与 diff 删除行
     逐字节平移；dark 块与 D3 表逐项一致；graphCanvasThemeColors 与 D4 一致。
  4. GraphCanvas：主题切换走独立 effect 就地重着色（forEachEdge + setSettings
     labelColor），不重建数据不重掷布局；colorSchemeRef 中转无 stale closure；
     Sigma.setSettings 合并语义已对源核实。
  5. 守卫有效性：突变验证无漏检路径（双底断言必要、红族钉阶双断言、
     删 token/wash 换值/ramp 调暗均红）。
  6. spec delta 逐条 SHALL/Scenario 覆盖。
  7. 遗留检查：无裸色值、无残缺 forceColorScheme（preview/test-utils 两处为
     design D5 明文保留的确定性基线）、无 console.log；四门禁实测绿。
- **P2 观察项处置**：
  - accent 对 accent-wash 余量最薄（4.597:1）→ 已在 theme.ts dark 块注释登记
    「调 siku ramp 前先看对比度守卫」余量备注（本轮落实）。
  - 壳页暗色块与 theme.ts 的同源仅靠注释约定、未做逐 token 测试断言 → 记录留痕，
    与亮色块既有模式一致，暂不加测试（壳页 token 集合小且变更频率低）。
  - docs/HANDOFF.md 陈旧的「暗色主题未实现」行 → tasks 4.4 整体重写 HANDOFF 时消解。
  - review.md 补录 1.4 红灯记录 → 即本文件。
