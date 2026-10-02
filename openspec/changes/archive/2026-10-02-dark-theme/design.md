# 设计：暗色三态主题的取值与接线

## D1 机制：库默认，零自造

主题三态（亮/暗/跟随系统）与持久化直接使用 ADR-0011 组件库内建能力：

- provider 默认 `auto`（跟随系统）；用户经切换入口选择后，手动值优先于系统并持久化（库默认存储键）。
- 首帧防闪烁用库导出的初始化脚本置入两处 HTML 入口，不自己写媒体查询内联脚本。

被否决的形态及理由：自造 `lib/theme.ts` 存储键 + 手写 `<html class>` 切换（kongming 形态，因其无组件库）——siku 已有组件库三态，再自造一套就是同一语义两套事实源，违反「用默认不胡乱覆盖」。

## D2 取值分层：`variables` 只留两态同值

resolver 现状是全部 token 挤在 `variables`（两态共用）+ `light` 只覆盖 body/text + `dark` 空块。方案相关 token 必须分流，否则暗色只能整体覆盖、无法两态并存：

| 分流后位置 | token |
|---|---|
| `variables`（两态同值，不动） | spacing/radius/font-*/weight-*/line-*/border-width/focus-outline/control-height 等度量与排印刻度 |
| `light`（现值平移） | canvas/surface/ink/ink-soft/ink-faint/border/border-strong/accent/accent-strong/accent-wash/success/warning/danger/warning-wash/warning-border/danger-wash/danger-border/shadow-card + mantine body/text |
| `dark`（新增，见 D3） | 同名一组 |

## D3 暗色取值：亮色值的明度反转，不同仓不另起色相

推导口径：保持现有色相家族（黛蓝墨底 + siku 蓝 accent），按 WCAG 对比度反算亮度档位；所有取值经对比度实测标定（阈值：暗底正文类 ≥4.5:1；wash 上文字 ≥4.5:1；边框为 hairline，与亮色同哲学低对比刻意为之）。

- canvas `#10161d` / surface `#182230`（亮色 ink 原值复用为暗色卡面，两态同族）
- ink `#e6ecf3`（对 canvas 15.29:1、surface 13.48:1）
- ink-soft `#a7b3c2`（8.55 / 7.53）、ink-faint `#8b98a8`（6.20 / 5.46）——辅助字两态都守住 ≥4.5:1，不允许「暗色辅助字降档」
- accent `#5e8af2`（ramp 4 阶）/ accent-strong `#8eafff`（3 阶）/ accent-wash `#0b225a`（9 阶）
- success `#5cb48d`、warning `#e0bc6c`、danger `#e29a99`（均取各自 ramp 亮色阶，对 canvas/surface ≥7:1）
- warning-wash `#482d05` + warning-border `#ad8420`；danger-wash `#632223` + danger-border `#bd5d5c`；wash 上文字取 ramp 3/4 阶（红 3 阶 `#e29a99` 对 wash 5.22:1，4 阶只有 3.84:1——红族 wash 文字必须用 3 阶，这是逐族标定值，不能一个阶位通吃）
- border `#2a3644` / border-strong `#3a4a5c`（hairline 分隔语义，非控件边界，不套 3:1）
- shadow-card `0 0.75rem 2rem rgb(0 0 0 / 0.35)`（暗色投影加深，亮色 ink 投影在暗底不可见）

红族的 wash 文字阶位差异说明一件事：对比度不能按「一个阶位通吃四个语义族」批量套，必须逐族标定——守卫按族逐条断言，不断言「同阶位」。

## D4 边线色：第二个 canvas 读不到 CSS 变量的例外

`GRAPH_EDGE_COLOR` 现为 `rgba(INK, 0.18)` 常量（注释已说明 canvas 绘制读不到 CSS 变量）。改为导出取值函数，由 `GraphCanvas` 按当前解析后的主题取亮/暗两值；社区分类色板不动（D3 已标的分隔语义不波及分类色）。这是 ks 里第二个「canvas 例外」，在 theme.ts 注释里与前例外并列登记，防止后来者误以为是漏改。

## D5 切换入口与守卫

- 入口放 header 操作区既有 `Group`（与服务状态徽章并列），图标按钮 + `aria-label` 明示目标态（「切换为暗色」/「切换为暗色」反转），移动端同在（该 Group `wrap="nowrap"` 常驻）。
- 守卫两态都进 `design-system.test.ts`：现有一条浅底断言，镜像一条暗底；另加切换入口组件测试（初始跟随系统 mock、点击写手动值、入口标签随目标态反转）。
- `preview.tsx` / `test-utils.tsx` 的 light 固定保留（预览与测试需要确定性基线，不动）；`test-utils` 另提供 dark 包裹入口供组件测试两态渲染。
