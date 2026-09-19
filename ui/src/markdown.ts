import type { MouseEvent } from "react";
import DOMPurify from "dompurify";
import { marked } from "marked";

/**
 * 只读 Markdown 安全渲染的唯一入口：marked 解析 → DOMPurify 清洗。
 *
 * 浏览/wiki/问答引用等任何用户可见的 Markdown 都必须经本函数输出：
 * DOMPurify 剥离脚本、事件处理器与 javascript: 等危险内容，保证「渲染
 * 不执行内嵌脚本」的只读安全承诺（change spec：防注入）。
 */
export function renderMarkdown(text: string): string {
  const html = marked.parse(text, { async: false });
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ["style", "form", "input", "button"],
    FORBID_ATTR: ["target"],
  });
}

/**
 * 只读链接守卫：渲染产物内的 <a> 一律拦截导航（href 保留供悬浮查看）。
 *
 * 桌面壳 webview 无地址栏与刷新按钮，点击语料内链接会把整窗导航离开应用；
 * 本视图为只读阅读面，不提供页内跳转语义。
 */
export function handleMarkdownClick(event: MouseEvent<HTMLElement>): void {
  const anchor = (event.target as HTMLElement).closest("a");
  if (anchor !== null) {
    event.preventDefault();
  }
}
