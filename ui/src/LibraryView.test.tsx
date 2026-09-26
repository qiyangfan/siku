import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { render } from "./test-utils";
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

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/全量重建/);
    await user.click(withinDialog(dialog, "取消"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
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
    await user.click(withinDialog(await screen.findByRole("dialog"), "确认重建"));

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
    await user.click(withinDialog(await screen.findByRole("dialog"), "确认重建"));

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

type RouteHandler = (method: string, init?: RequestInit) => unknown;

function mockRoutes(routes: Record<string, RouteHandler>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = typeof input === "string" ? input : String(input instanceof URL ? input : input.url);
    const method = init?.method ?? "GET";
    const handler = routes[url];
    if (handler === undefined) {
      throw new Error(`unexpected fetch: ${method} ${url}`);
    }
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve(handler(method, init)),
    } as Response);
  });
}

const emptySyncSources = { sources: [] };

const oneSyncSource = {
  sources: [
    {
      id: "sync-1",
      path: "/Users/you/Documents/notes",
      enabled: true,
      created_at: "2026-09-23T10:00:00+08:00",
      last_scan_at: null,
    },
  ],
};

const listingWithMarked = {
  sources: [
    {
      name: "旧版报告.pdf",
      path: "superseded/报告--a1b2c3d4e5f6.pdf",
      source_hash: "c".repeat(64),
      ingest_status: "superseded",
      index_status: "missing",
      origin_path: "/Users/you/Documents/notes/报告.pdf",
    },
    {
      name: "缺失笔记.md",
      path: "attachments/缺失笔记--b2c3d4e5f6a1.md",
      source_hash: "d".repeat(64),
      ingest_status: "missing",
      index_status: "missing",
      origin_path: null,
    },
  ],
};

describe("来源目录同步", () => {
  it("展开后可添加来源目录并展示登记清单", async () => {
    const user = userEvent.setup();
    const fetchSpy = mockRoutes({
      "/api/library": () => emptyListing,
      "/api/library/sources": () => emptySyncSources,
      "/api/library/scan-settings": () => ({ interval_secs: 300 }),
    });
    render(<LibraryView />);

    await screen.findByText("资料库还是空的");
    expect(fetchSpy.mock.calls.filter(([url]) => String(url) === "/api/library/sources")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "来源目录与自动扫描" }));

    expect(
      await screen.findByText(/尚未登记来源目录/),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText("来源目录路径"), "/Users/you/Documents/notes");
    fetchSpy.mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : String(input);
      const method = init?.method ?? "GET";
      if (url === "/api/library/sources" && method === "POST") {
        expect(String(init?.body)).toContain("/Users/you/Documents/notes");
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(oneSyncSource.sources[0]),
        } as Response);
      }
      if (url === "/api/library/sources") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(oneSyncSource),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(emptyListing),
      } as Response);
    });
    await user.click(screen.getByRole("button", { name: "添加来源" }));

    expect(await screen.findByText("/Users/you/Documents/notes")).toBeInTheDocument();
    expect(screen.getByText("已启用")).toBeInTheDocument();
    expect(screen.getByText("从未扫描")).toBeInTheDocument();
  });

  it("立即扫描触发扫描任务并展示入库结果", async () => {
    const user = userEvent.setup();
    const scanJob = (state: string) => ({
      job_id: "scan-1",
      kind: "scan",
      state,
      phase: "scanning",
      total: 1,
      done: 1,
      failed: 0,
      current: null,
      items: [
        { name: "新文档.pdf", path: "attachments/新文档--a1b2c3d4e5f6.pdf", status: "created", detail: null },
      ],
      error: null,
    });
    mockRoutes({
      "/api/library": () => emptyListing,
      "/api/library/sources": () => oneSyncSource,
      "/api/library/scan-settings": () => ({ interval_secs: 300 }),
      "/api/library/scan": (method, init) => {
        expect(method).toBe("POST");
        expect(String(init?.body)).toContain('"full":false');
        return scanJob("succeeded");
      },
    });
    render(<LibraryView />);

    await screen.findByText("资料库还是空的");
    await user.click(screen.getByRole("button", { name: "来源目录与自动扫描" }));
    await screen.findByText("/Users/you/Documents/notes");
    await user.click(screen.getByRole("button", { name: "立即扫描" }));

    expect(await screen.findByText("扫描完成：处理 1 项动作。")).toBeInTheDocument();
  });

  it("清单展示缺失、已替代徽标与来源路径", async () => {
    mockRoutes({ "/api/library": () => listingWithMarked });
    render(<LibraryView />);

    const list = await screen.findByRole("list", { name: "资料库来源清单" });
    expect(list).toHaveTextContent("来源缺失");
    expect(list).toHaveTextContent("已被替代");
    expect(list).toHaveTextContent("来自 /Users/you/Documents/notes/报告.pdf");
  });

  it("清理需经确认对话框，取消时不发请求；确认后物理清理", async () => {
    const user = userEvent.setup();
    const purgeJob = {
      job_id: "purge-1",
      kind: "purge",
      state: "succeeded",
      phase: "purging",
      total: 2,
      done: 2,
      failed: 0,
      current: null,
      items: [
        { name: "旧版报告.pdf", path: "superseded/报告--a1b2c3d4e5f6.pdf", status: "removed", detail: "已物理清理。" },
        { name: "缺失笔记.md", path: "attachments/缺失笔记--b2c3d4e5f6a1.md", status: "removed", detail: "已物理清理。" },
      ],
      error: null,
    };
    const fetchSpy = mockRoutes({
      "/api/library": () => listingWithMarked,
      "/api/library/purge": (method, init) => {
        expect(method).toBe("POST");
        expect(String(init?.body)).toContain('"confirm":true');
        return purgeJob;
      },
    });
    render(<LibraryView />);

    const list = await screen.findByRole("list", { name: "资料库来源清单" });
    expect(list).toHaveTextContent("来源缺失");
    await user.click(screen.getByRole("button", { name: "清理失效文档（2）" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("确认清理 2 项失效文档？");
    await user.click(withinDialog(dialog, "取消"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(
      fetchSpy.mock.calls.filter(([url]) => String(url) === "/api/library/purge"),
    ).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "清理失效文档（2）" }));
    await user.click(withinDialog(await screen.findByRole("dialog"), "确认清理"));
    expect(await screen.findByText("清理完成：已物理移除 2 项失效文档。")).toBeInTheDocument();
  });

  it("清理失效文档按钮带危险配色，可清零时禁用并有释义 tooltip", async () => {
    mockRoutes({ "/api/library": () => listingWithMarked });
    render(<LibraryView />);

    const button = await screen.findByRole("button", { name: "清理失效文档（2）" });
    expect(button).toHaveClass("button-danger");
    expect(button).toHaveAccessibleDescription(/来源缺失/);

    mockRoutes({ "/api/library": () => emptyListing });
    cleanup();
    render(<LibraryView />);
    const idleButton = await screen.findByRole("button", { name: "清理失效文档" });
    expect(idleButton).toBeDisabled();
  });

  it("拖拽文件到导入区按点击选择同路发起摄取", async () => {
    const runningJob = {
      job_id: "job-drop",
      kind: "ingest",
      state: "running",
      phase: "ingesting",
      total: 1,
      done: 0,
      failed: 0,
      current: "拖入.pdf",
      items: [],
      error: null,
    };
    mockRouter([
      () => emptyListing,
      (url, method, init) => {
        expect(url).toBe("/api/library/ingest");
        expect(method).toBe("POST");
        expect(initBodyHasFile(init)).toBe(true);
        return runningJob;
      },
    ]);
    render(<LibraryView />);

    await screen.findByText("资料库还是空的");
    const dropzone = screen.getByRole("button", { name: /导入文件：点击选择或拖入文档/ });
    const file = new File(["pdf-bytes"], "拖入.pdf", { type: "application/pdf" });
    fireEvent.drop(dropzone, { dataTransfer: { files: [file] } });

    expect(await screen.findByText(/正在摄取/)).toBeInTheDocument();
  });

  it("导入区拖拽悬停有高亮反馈，拖离后消退", async () => {
    mockRouter([() => emptyListing]);
    render(<LibraryView />);

    const dropzone = await screen.findByRole("button", { name: /导入文件：点击选择或拖入文档/ });
    expect(dropzone).not.toHaveClass("library-dropzone-active");
    fireEvent.dragOver(dropzone);
    expect(dropzone).toHaveClass("library-dropzone-active");
    fireEvent.dragLeave(dropzone);
    expect(dropzone).not.toHaveClass("library-dropzone-active");
  });

  it("来源清单状态徽标带可读释义 tooltip", async () => {
    mockRoutes({ "/api/library": () => listingWithMarked });
    render(<LibraryView />);

    const list = await screen.findByRole("list", { name: "资料库来源清单" });
    const missingBadge = within(list).getByText("来源缺失");
    expect(missingBadge).toHaveAccessibleDescription(/原件文件已不存在/);
    const supersededBadge = within(list).getByText("已被替代");
    expect(supersededBadge).toHaveAccessibleDescription(/已被替代/);
  });
});
