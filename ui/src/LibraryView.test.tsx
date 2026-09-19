import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LibraryView } from "./LibraryView";

type Handler = (url: string, method: string, init?: RequestInit) => unknown;

function mockRouter(handlers: Handler[]) {
  const queue = [...handlers];
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = typeof input === "string" ? input : String(input instanceof URL ? input : input.url);
    const method = init?.method ?? "GET";
    const handler = queue.shift();
    if (handler === undefined) {
      throw new Error(`unexpected fetch: ${method} ${url}`);
    }
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve(handler(url, method, init)),
    } as Response);
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const emptyListing = { sources: [] };

const twoSources = {
  sources: [
    {
      name: "论文.pdf",
      path: "attachments/document--a1b2c3d4e5f6.pdf",
      source_hash: "a".repeat(64),
      ingest_status: "ingested",
      index_status: "indexed",
    },
    {
      name: "旧笔记.md",
      path: "attachments/old--b2c3d4e5f6a1.md",
      source_hash: "b".repeat(64),
      ingest_status: "stale",
      index_status: "stale",
    },
  ],
};

describe("资料库视图", () => {
  it("空资料库展示导入引导与支持格式说明，不渲染空白列表", async () => {
    mockRouter([(url, method) => {
      expect(url).toBe("/api/library");
      expect(method).toBe("GET");
      return emptyListing;
    }]);
    render(<LibraryView />);

    expect(await screen.findByText("资料库还是空的")).toBeInTheDocument();
    expect(screen.getByText(/支持格式：/)).toHaveTextContent("PDF、Word、PPT、Excel、EPUB、HTML、Markdown");
    expect(screen.queryByRole("list", { name: "资料库来源清单" })).not.toBeInTheDocument();
  });

  it("来源清单展示名称与摄取、索引状态徽标", async () => {
    mockRouter([() => twoSources]);
    render(<LibraryView />);

    const list = await screen.findByRole("list", { name: "资料库来源清单" });
    expect(list).toHaveTextContent("论文.pdf");
    expect(list).toHaveTextContent("已摄取");
    expect(list).toHaveTextContent("已索引");
    expect(list).toHaveTextContent("待重抽");
    expect(list).toHaveTextContent("索引待更新");
  });

  it("导入后跟踪进度并在结束时刷新清单", async () => {
    const user = userEvent.setup();
    const runningJob = {
      job_id: "job-1",
      kind: "ingest",
      state: "running",
      phase: "ingesting",
      total: 1,
      done: 0,
      failed: 0,
      current: "论文.pdf",
      items: [],
      error: null,
    };
    const doneJob = {
      ...runningJob,
      state: "succeeded",
      done: 1,
      current: null,
      items: [
        { name: "论文.pdf", path: "attachments/document--a1b2.pdf", status: "created", detail: null },
      ],
    };
    const refreshed = { sources: [twoSources.sources[0]] };
    mockRouter([
      () => emptyListing,
      (url, method, init) => {
        expect(url).toBe("/api/library/ingest");
        expect(method).toBe("POST");
        expect(initBodyHasFile(init)).toBe(true);
        return runningJob;
      },
      () => doneJob,
      () => refreshed,
    ]);
    render(<LibraryView />);

    await screen.findByText("资料库还是空的");
    const input = screen.getByLabelText("选择要导入的文件");
    await user.upload(input, [new File(["pdf-bytes"], "论文.pdf", { type: "application/pdf" })]);

    expect(await screen.findByText("导入完成：1 个文件成功。")).toBeInTheDocument();
    await waitFor(
      () => expect(screen.getByRole("list", { name: "资料库来源清单" })).toHaveTextContent("论文.pdf"),
      { timeout: 3000 },
    );
  });

  it("全量重建需经确认对话框，取消时不发任何请求", async () => {
    const user = userEvent.setup();
    const fetchSpy = mockRouter([() => emptyListing]);
    render(<LibraryView />);

    await screen.findByText("资料库还是空的");
    await user.click(screen.getByRole("button", { name: "全量重建索引" }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(/全量重建/);
    await user.click(withinDialog(dialog, "取消"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      fetchSpy.mock.calls.filter(([url]) => String(url).includes("/api/library/rebuild")),
    ).toHaveLength(0);
  });

  it("确认后触发重建并展示完成反馈", async () => {
    const user = userEvent.setup();
    const rebuildJob = {
      job_id: "job-2",
      kind: "rebuild",
      state: "running",
      phase: "indexing",
      total: 0,
      done: 0,
      failed: 0,
      current: null,
      items: [],
      error: null,
    };
    const doneJob = { ...rebuildJob, state: "succeeded" };
    mockRouter([
      () => twoSources,
      (url, method, init) => {
        expect(url).toBe("/api/library/rebuild");
        expect(method).toBe("POST");
        expect(String(init?.body)).toContain('"confirm":true');
        return rebuildJob;
      },
      () => doneJob,
      () => twoSources,
    ]);
    render(<LibraryView />);

    await screen.findByRole("list", { name: "资料库来源清单" });
    await user.click(screen.getByRole("button", { name: "全量重建索引" }));
    await user.click(withinDialog(screen.getByRole("dialog"), "确认重建"));

    expect(await screen.findByText("索引全量重建完成。")).toBeInTheDocument();
  });

  it("任务失败时展示后端中文指引", async () => {
    const user = userEvent.setup();
    const failedJob = {
      job_id: "job-3",
      kind: "rebuild",
      state: "failed",
      phase: "indexing",
      total: 0,
      done: 0,
      failed: 0,
      current: null,
      items: [],
      error: "已建索引的模型配置与当前不一致：请执行全量重建。",
    };
    mockRouter([
      () => emptyListing,
      () => failedJob,
      () => emptyListing,
    ]);
    render(<LibraryView />);

    await screen.findByText("资料库还是空的");
    await user.click(screen.getByRole("button", { name: "全量重建索引" }));
    await user.click(withinDialog(screen.getByRole("dialog"), "确认重建"));

    expect(
      await screen.findByText("已建索引的模型配置与当前不一致：请执行全量重建。"),
    ).toBeInTheDocument();
  });

  it("触发冲突（409）时展示稳定错误提示", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : String(input instanceof URL ? input : input.url);
      if (url === "/api/library") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(emptyListing) } as Response);
      }
      return Promise.resolve({
        ok: false,
        json: () =>
          Promise.resolve({ code: "library_job_busy", message: "已有一个摄取或重建任务正在执行。" }),
      } as Response);
    });
    render(<LibraryView />);

    await screen.findByText("资料库还是空的");
    const input = screen.getByLabelText("选择要导入的文件");
    await user.upload(input, [new File(["x"], "a.md")]);

    expect(await screen.findByText("已有一个摄取或重建任务正在执行。")).toBeInTheDocument();
  });
});

function initBodyHasFile(init?: RequestInit): boolean {
  return init?.body instanceof FormData && Array.from(init.body.getAll("files")).length > 0;
}

function withinDialog(dialog: HTMLElement, name: string): HTMLElement {
  const button = Array.from(dialog.querySelectorAll("button")).find(
    (candidate) => candidate.textContent === name,
  );
  if (button === undefined) {
    throw new Error(`button ${name} not found in dialog`);
  }
  return button;
}
