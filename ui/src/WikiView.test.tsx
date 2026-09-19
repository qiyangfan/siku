import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { WikiEntries, WikiEntryDetail } from "./api";
import { WikiView } from "./WikiView";

const entries: WikiEntries = {
  entries: [
    { community_id: 1, title: "社区 0001", generated_at: "2026-09-19T10:00:00+08:00" },
    { community_id: 2, title: "社区 0002", generated_at: "2026-09-19T10:00:00+08:00" },
  ],
};

const entryDetail: WikiEntryDetail = {
  community_id: 1,
  title: "社区 0001",
  content: "# 社区 0001\n\n## 摘要\n\n本地优先的知识库。",
  generated_at: "2026-09-19T10:00:00+08:00",
};

function jsonResponse(payload: unknown, ok = true) {
  return Promise.resolve({ ok, json: () => Promise.resolve(payload) } as Response);
}

function mockFetchByRoutes(routes: Record<string, () => ReturnType<typeof jsonResponse>>) {
  vi.spyOn(globalThis, "fetch").mockImplementation((input: string | URL | Request) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const route = routes[url.replace(/^https?:\/\/[^/]+/, "")];
    if (route === undefined) {
      throw new Error(`unexpected fetch: ${url}`);
    }
    return route();
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("wiki 视图", () => {
  it("渲染条目清单并阅读：内容、生成时间与可重建提示", async () => {
    mockFetchByRoutes({
      "/api/wiki/entries": () => jsonResponse(entries),
      "/api/wiki/entries/1": () => jsonResponse(entryDetail),
    });
    const user = userEvent.setup();

    render(<WikiView />);
    expect(await screen.findByText("共 2 个社区条目；内容由模型基于语料生成。")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /社区 0001/ }));

    expect(await screen.findByRole("heading", { level: 3, name: "社区 0001" })).toBeInTheDocument();
    expect(screen.getByText("本地优先的知识库。")).toBeInTheDocument();
    expect(screen.getByText(/生成于 .* ·/)).toBeInTheDocument();
    expect(screen.getByText(/siku wiki/)).toBeInTheDocument();
  });

  it("wiki 未生成时给出可行动的空态提示", async () => {
    mockFetchByRoutes({
      "/api/wiki/entries": () =>
        jsonResponse({ code: "wiki_missing", message: "wiki 尚未生成。" }, false),
    });

    render(<WikiView />);
    expect(await screen.findByText("wiki 尚未生成")).toBeInTheDocument();
    expect(screen.getByText(/siku graph/)).toBeInTheDocument();
  });

  it("清单读取失败时展示告警并支持重试", async () => {
    mockFetchByRoutes({
      "/api/wiki/entries": () =>
        jsonResponse({ code: "internal_error", message: "服务内部错误。" }, false),
    });

    render(<WikiView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("服务内部错误。");
    expect(screen.getByRole("button", { name: "重试读取" })).toBeInTheDocument();
  });
});
