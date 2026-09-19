import "@testing-library/jest-dom/vitest";

// jsdom 无 WebGL：sigma 在模块加载期即引用 WebGL2 上下文类型，先垫桩；
// 画布实例在单测中一律经 vi.mock 替身，不会真正创建渲染器。
if (typeof globalThis.WebGL2RenderingContext === "undefined") {
  Object.assign(globalThis, {
    WebGL2RenderingContext: class WebGL2RenderingContextStub {},
  });
}
if (typeof globalThis.WebGLRenderingContext === "undefined") {
  Object.assign(globalThis, {
    WebGLRenderingContext: class WebGLRenderingContextStub {},
  });
}
