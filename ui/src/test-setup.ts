import "@testing-library/jest-dom/vitest";

if (typeof window.matchMedia !== "function") {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (media: string): MediaQueryList => ({
      matches: false,
      media,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
}

if (typeof globalThis.ResizeObserver === "undefined") {
  Object.assign(globalThis, {
    ResizeObserver: class ResizeObserverStub {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  });
}

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
