import { describe, expect, it, vi } from "vitest";
import { handleMarkdownClick, renderMarkdown } from "./markdown";

describe("只读安全 Markdown 渲染", () => {
  it("渲染常规结构（标题/加粗/列表/链接）", () => {
    const view = renderMarkdown(
      "# 标题\n\n**加粗** 与 [链接](https://example.com)",
    );
    expect(view).toContain("<h1>标题</h1>");
    expect(view).toContain("<strong>加粗</strong>");
    expect(view).toContain('href="https://example.com"');
  });

  it("剥除内嵌脚本与事件处理器", () => {
    const view = renderMarkdown(
      'hello <script>alert(1)</script><img src=x onerror="alert(1)">world',
    );
    expect(view).not.toContain("<script");
    expect(view).not.toContain("onerror");
    expect(view).toContain("hello");
    expect(view).toContain("world");
  });

  it("剥除 javascript: 危险链接", () => {
    const view = renderMarkdown("[点我](javascript:alert(1))");
    expect(view).not.toContain("javascript:");
  });

  it("剥除 iframe 与 style 注入", () => {
    const view = renderMarkdown(
      '<iframe src="https://evil.example"></iframe><style>body{}</style>',
    );
    expect(view).not.toContain("<iframe");
    expect(view).not.toContain("<style");
  });

  it("链接守卫拦截渲染产物内 <a> 的默认导航", () => {
    const container = document.createElement("div");
    container.innerHTML = renderMarkdown("[外链](https://example.com)");
    const anchor = container.querySelector("a");
    expect(anchor).not.toBeNull();
    const preventDefault = vi.fn();
    const event = {
      target: anchor,
      preventDefault,
    } as unknown as Parameters<typeof handleMarkdownClick>[0];
    handleMarkdownClick(event);
    expect(preventDefault).toHaveBeenCalled();
  });

  it("链接守卫不拦截非链接区域的点击", () => {
    const container = document.createElement("div");
    container.innerHTML = renderMarkdown("普通段落");
    const preventDefault = vi.fn();
    const event = {
      target: container,
      preventDefault,
    } as unknown as Parameters<typeof handleMarkdownClick>[0];
    handleMarkdownClick(event);
    expect(preventDefault).not.toHaveBeenCalled();
  });
});
