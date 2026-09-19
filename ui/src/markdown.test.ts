import { describe, expect, it, vi } from "vitest";
import { handleMarkdownClick, renderMarkdown } from "./markdown";

describe("只读安全 Markdown 渲染", () => {
  it("渲染常规结构（标题/加粗/列表/链接）", () => {
    const html = renderMarkdown("# 标题\n\n**加粗** 与 [链接](https://example.com)");
    expect(html).toContain("<h1>标题</h1>");
    expect(html).toContain("<strong>加粗</strong>");
    expect(html).toContain('href="https://example.com"');
  });

  it("剥除内嵌脚本与事件处理器", () => {
    const html = renderMarkdown(
      'hello <script>alert(1)</script><img src=x onerror="alert(1)">world',
    );
    expect(html).not.toContain("<script");
    expect(html).not.toContain("onerror");
    expect(html).toContain("hello");
    expect(html).toContain("world");
  });

  it("剥除 javascript: 危险链接", () => {
    const html = renderMarkdown("[点我](javascript:alert(1))");
    expect(html).not.toContain("javascript:");
  });

  it("剥除 iframe 与 style 注入", () => {
    const html = renderMarkdown('<iframe src="https://evil.example"></iframe><style>body{}</style>');
    expect(html).not.toContain("<iframe");
    expect(html).not.toContain("<style");
  });

  it("链接守卫拦截渲染产物内 <a> 的默认导航", () => {
    const container = document.createElement("div");
    container.innerHTML = renderMarkdown("[外链](https://example.com)");
    const anchor = container.querySelector("a");
    expect(anchor).not.toBeNull();
    const event = {
      target: anchor,
      preventDefault: vi.fn(),
    } as unknown as Parameters<typeof handleMarkdownClick>[0];
    handleMarkdownClick(event);
    expect(event.preventDefault).toHaveBeenCalled();
  });

  it("链接守卫不拦截非链接区域的点击", () => {
    const container = document.createElement("div");
    container.innerHTML = renderMarkdown("普通段落");
    const event = {
      target: container,
      preventDefault: vi.fn(),
    } as unknown as Parameters<typeof handleMarkdownClick>[0];
    handleMarkdownClick(event);
    expect(event.preventDefault).not.toHaveBeenCalled();
  });
});
