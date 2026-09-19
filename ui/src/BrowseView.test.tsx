import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { NoteDetail, NotesPage } from "./api";
import { BrowseView } from "./BrowseView";

const noteSummary = {
  source_id: "aa000001",
  source_name: "architecture.md",
  note_path: "notes/architecture.md",
  source_hash: "a".repeat(64),
  extractor: "MarkdownExtractor",
};

const page1: NotesPage = {
  notes: [noteSummary],
  total: 2,
  page: 1,
  page_size: 1,
};

const page2: NotesPage = {
  notes: [
    {
      source_id: "bb000002",
      source_name: "glossary.md",
      note_path: "notes/glossary.md",
      source_hash: "b".repeat(64),
      extractor: "MarkdownExtractor",
    },
  ],
  total: 2,
  page: 2,
  page_size: 1,
};

const noteDetail: NoteDetail = {
  ...noteSummary,
  anchors: ["背景", "结论"],
  content: "# 样例文档\n\n这是**加粗**正文。",
};

function jsonResponse(payload: unknown, ok = true) {
  return Promise.resolve({ ok, json: () => Promise.resolve(payload) } as Response);
}

/** 按 URL 路由的 fetch 替身（只覆盖本用例需要的路径；路由函数收到完整 url）。 */
function mockFetchByRoutes(
  routes: Record<string, (url: string) => ReturnType<typeof jsonResponse>>,
) {
  vi.spyOn(globalThis, "fetch").mockImplementation((input: string | URL | Request) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    const route = routes[path];
    if (route === undefined) {
      throw new Error(`unexpected fetch: ${url}`);
    }
    return route(url);
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("浏览视图", () => {
  it("渲染清单并打开单篇：只读 Markdown 与来源锚点信息", async () => {
    mockFetchByRoutes({
      "/api/notes": () => jsonResponse(page1),
      "/api/notes/aa000001": () => jsonResponse(noteDetail),
    });
    const user = userEvent.setup();

    render(<BrowseView />);
    const item = await screen.findByRole("button", { name: /architecture\.md/ });
    await user.click(item);

    expect(await screen.findByRole("heading", { name: "architecture.md" })).toBeInTheDocument();
    expect(screen.getAllByText("notes/architecture.md").length).toBeGreaterThan(0);
    expect(screen.getByText("抽取器：MarkdownExtractor")).toBeInTheDocument();
    expect(screen.getByText(/源 aaaaaaaa/)).toBeInTheDocument();
    expect(screen.getByText("背景")).toBeInTheDocument();
    expect(screen.getByText("结论")).toBeInTheDocument();
    expect(screen.getByText("加粗")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "编辑" })).not.toBeInTheDocument();
  });

  it("渲染用户内容时不执行内嵌脚本（防注入证据）", async () => {
    mockFetchByRoutes({
      "/api/notes": () => jsonResponse(page1),
      "/api/notes/aa000001": () =>
        jsonResponse({
          ...noteDetail,
          content: '正文 <script>alert(1)</script><img src=x onerror="alert(2)">结尾',
        }),
    });
    const user = userEvent.setup();

    render(<BrowseView />);
    await user.click(await screen.findByRole("button", { name: /architecture\.md/ }));
    await screen.findByRole("heading", { name: "architecture.md" });

    // 脚本被剥除、事件处理器被剥除（DOMPurify），正文文本保留
    expect(document.querySelector("script")).not.toBeInTheDocument();
    const image = document.querySelector("img");
    expect(image).not.toBeNull();
    expect(image).not.toHaveAttribute("onerror");
  });

  it("分页：第二页数据经 page 参数加载", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => jsonResponse(page1))
      .mockImplementation((input: string | URL | Request) => {
        const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        expect(url).toContain("page=2");
        return jsonResponse(page2);
      });
    const user = userEvent.setup();

    render(<BrowseView />);
    await waitFor(() => expect(screen.getByText("第 1 / 2 页")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "下一页" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /glossary\.md/ })).toBeInTheDocument(),
    );
    expect(screen.getByText("第 2 / 2 页")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalled();
  });

  it("空库与清单错误各走对应空态/告警", async () => {
    mockFetchByRoutes({
      "/api/notes": () => jsonResponse({ notes: [], total: 0, page: 1, page_size: 20 }),
    });
    const { unmount } = render(<BrowseView />);
    expect(await screen.findByText("还没有可阅读的笔记")).toBeInTheDocument();
    unmount();

    mockFetchByRoutes({
      "/api/notes": () => jsonResponse({ code: "internal_error", message: "服务内部错误。" }, false),
    });
    render(<BrowseView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("服务内部错误。");
  });

  it("翻页后落在合法空页：保留翻页器并提示返回，不误报空库", async () => {
    // 场景：浏览期间资料被删除，第二页从有内容变为合法空页
    mockFetchByRoutes({
      "/api/notes": (url) =>
        url.includes("page=2")
          ? jsonResponse({ notes: [], total: 1, page: 2, page_size: 1 })
          : jsonResponse({
              notes: [
                {
                  source_id: "aa000001",
                  source_name: "only.md",
                  note_path: "notes/only.md",
                  source_hash: "a".repeat(64),
                  extractor: "MarkdownExtractor",
                },
                {
                  source_id: "bb000002",
                  source_name: "removed.md",
                  note_path: "notes/removed.md",
                  source_hash: "b".repeat(64),
                  extractor: "MarkdownExtractor",
                },
              ],
              total: 2,
              page: 1,
              page_size: 1,
            }),
    });
    const user = userEvent.setup();

    render(<BrowseView />);
    await screen.findByRole("button", { name: /only\.md/ });
    await user.click(screen.getByRole("button", { name: "下一页" }));

    expect(await screen.findByText(/本页无内容/)).toBeInTheDocument();
    expect(screen.queryByText("还没有可阅读的笔记")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上一页" })).toBeEnabled();
  });

  it("打开新笔记失败时清掉旧内容，错误卡不与旧正文同屏", async () => {
    const twoNotes = {
      notes: [
        noteSummary,
        {
          source_id: "bb000002",
          source_name: "glossary.md",
          note_path: "notes/glossary.md",
          source_hash: "b".repeat(64),
          extractor: "MarkdownExtractor",
        },
      ],
      total: 2,
      page: 1,
      page_size: 2,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation((input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
      if (path === "/api/notes") {
        return jsonResponse(twoNotes);
      }
      if (path === "/api/notes/aa000001") {
        return jsonResponse(noteDetail);
      }
      if (path === "/api/notes/bb000002") {
        return jsonResponse({ code: "internal_error", message: "服务内部错误。" }, false);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    const user = userEvent.setup();

    render(<BrowseView />);
    await user.click(await screen.findByRole("button", { name: /architecture\.md/ }));
    expect(await screen.findByRole("heading", { name: "architecture.md" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /glossary\.md/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("服务内部错误。");
    // 旧正文必须已清掉：标题与正文不再同屏
    expect(screen.queryByRole("heading", { name: "architecture.md" })).not.toBeInTheDocument();
  });

  it("翻页失败保留旧页并在分页器旁渲染错误", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
      if (path === "/api/notes" && url.includes("page=2")) {
        return jsonResponse({ code: "internal_error", message: "翻页失败。" }, false);
      }
      if (path === "/api/notes") {
        return jsonResponse({
          notes: [
            {
              source_id: "aa000001",
              source_name: "only.md",
              note_path: "notes/only.md",
              source_hash: "a".repeat(64),
              extractor: "MarkdownExtractor",
            },
          ],
          total: 2,
          page: 1,
          page_size: 1,
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    const user = userEvent.setup();

    render(<BrowseView />);
    await screen.findByRole("button", { name: /only\.md/ });
    await user.click(screen.getByRole("button", { name: "下一页" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("翻页失败。");
    // 旧页保留可读
    expect(screen.getByRole("button", { name: /only\.md/ })).toBeInTheDocument();
  });

  it("错误状态码返回非 JSON 体时回退稳定错误文案", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve({
        ok: false,
        status: 502,
        json: () => Promise.reject(new SyntaxError("bad json")),
      } as unknown as Response),
    );
    render(<BrowseView />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("请求失败，请稍后重试。");
  });
});
