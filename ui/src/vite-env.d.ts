// TS 6.0 起 noUncheckedSideEffectImports 默认开启（TS 7 前瞻默认值）：
// CSS 副作用 import 需要显式环境声明
declare module "*.css";

declare module "*.css?raw" {
  const stylesheet: string;
  export default stylesheet;
}

declare module "*.html?raw" {
  const markup: string;
  export default markup;
}
