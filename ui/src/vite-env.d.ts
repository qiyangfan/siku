declare module "*.css?raw" {
  const stylesheet: string;
  export default stylesheet;
}

declare module "*.html?raw" {
  const markup: string;
  export default markup;
}
