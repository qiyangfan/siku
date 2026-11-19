# 设计：前端门禁的阈值来源与抑制边界

## Context

各工具首次接入，必须先测基线再设阈值；不能为了过闸改默认参数或全局降级。

## Decisions

### D1 格式与静态检查

prettier 只作用于 `ui/`（`.prettierignore` 排除 lock 与 src-tauri）；stylelint 用
standard 配置。`index.html` 的内联主题脚本加 `<!-- prettier-ignore -->`，因为它
被 `design-system.test.ts` 逐字比对，格式化会破坏该防漂移守卫。

### D2 供应商类名与跨上下文顺序

Mantine 生成 `.mantine-Button-root` 这类类名，`selector-class-pattern` 扩展为
「kebab-case 或 mantine-*」。`no-descending-specificity` 对跨组件上下文（citation
与 library/markdown）的 2 处误报逐行禁用并写原因，其余 3 处通过重排顺序修复。

### D3 a11y 点击委托

Markdown 只读容器把点击委托给内部 `<a>`，键盘 Enter 同样产生 click 冒泡；
容器本身不可交互，故 2 处逐行禁用两条规则并写原因。其余 a11y 规则全部开启。

### D4 重复率与覆盖率阈值

jscpd 基线 4.63% → 阈值 5.2%（+0.5，只降不升）。vitest 覆盖率在 `include` 全量
src 后基线为语句 79.94 / 分支 75.58 / 函数 81.31 / 行 79.72，阈值向下取整。

### D5 依赖边界与死代码

depcruise 的 `no-orphans` 保持 warn（`vite-env.d.ts` 为类型声明，天然无 import）；
knip 清掉未使用的 default export 与导出类型，入口显式声明 preview（main 由
index.html 自动识别）。

### D6 复杂度取工具默认 20，行数沿用 1000

ESLint `complexity` 的默认上限是 20，直接写 `"error"` 使用默认值；`max-lines` 显式取
1000（与 Python 模块上限同口径，默认 300 会把现有视图全部判红）。7 处热点按展示块
提取子组件：纯 JSX 搬运、不改请求/状态/DOM 结构与文案。`LibraryView` 超过 1000 行后
拆出 `LibraryPanels.tsx`，避免用阈值掩盖文件体积。

## Risks / Trade-offs

- [ESLint 10 与 jsx-a11y peer 不匹配] → `.npmrc` legacy-peer-deps 统一本地与 CI；
  规则实测生效。
- [覆盖率 include 全量 src] → 未导入文件计入分母，阈值相应下调（基线取整）。

## Migration Plan

无。回滚 = 还原 ui 配置与 package.json、删除新增工具依赖。

## Open Questions

无。
