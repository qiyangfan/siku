import type { MouseEvent } from "react";
import DOMPurify from "dompurify";
import { marked } from "marked";

/**
 * 只读 Markdown 渲染入口：marked 解析后经 DOMPurify 清洗，渲染不执行内嵌脚本。
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
 * 拦截渲染产物内的链接导航；桌面壳没有地址栏，点击链接会离开应用。
 */
export function handleMarkdownClick(event: MouseEvent<HTMLElement>): void {
  const anchor = (event.target as HTMLElement).closest("a");
  if (anchor !== null) {
    event.preventDefault();
  }
}
