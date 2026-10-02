import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { render } from "./test-utils";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import App from "./App";

// jsdom 无 WebGL：画布以替身组件呈现（点选按钮触发 onSelect，仅联动用例触达）
vi.mock("./GraphCanvas", () => ({
  GraphCanvas: (props: {
    selectedId: string | null;
    onSelect: (node: {
      entity_id: string;
      name: string;
      type: string;
      degree: number;
      community_id: number;
    }) => void;
  }) =>
    React.createElement(
      "button",
      {
        type: "button",
        "data-testid": "graph-canvas-stub",
        onClick: () =>
          props.onSelect({
            entity_id: "e-a",
            name: "Alpha Kernel",
            type: "系统",
            degree: 1,
            community_id: 0,
          }),
      },
      props.selectedId === null ? "模拟点选节点" : "已选中节点",
    ),
}));

const answer = {
  request_id: "request-123",
  question: "边界是什么？",
  answer: "内核只通过 localhost HTTP API 暴露能力。",
  insufficient_evidence: false,
  citations: [
    {
      citation_id: "C1",
      source_name: "architecture.md",
      note_path: "notes/architecture.md",
      anchor: "本地优先",
      chunk_id: "chunk-1",
      source_hash: "a".repeat(64),
      text: "UI 与内核只通过 localhost HTTP API 通信。",
    },
  ],
  retrieval: { top_k: 6, candidate_k: 30, result_count: 1 },
  model: "fake-answer",
};

function response(payload: unknown, ok = true) {
  return Promise.resolve({ ok, json: () => Promise.resolve(payload) } as Response);
}

function emptyNotesResponse() {
  return response({ notes: [], total: 0, page: 1, page_size: 5 });
}

function emptyWikiResponse() {
  return response({ entries: [] });
}

const emptyChannelView = {
  base_url: null,
  model: null,
  api_key_env: null,
  api_key_set: false,
  env_overrides: [],
};

function makeSettings(ready: boolean, missing: string[]) {
  return {
    config_path: "/tmp/config.toml",
    llm: { ...emptyChannelView },
    embedding: { ...emptyChannelView },
    rerank: { ...emptyChannelView },
    ask_readiness: { ready, missing },
  };
}

const NOT_READY_SETTINGS = makeSettings(false, [
  "llm.api_key",
  "embedding.base_url",
  "embedding.model",
]);

function viewTab(label: string) {
  return within(screen.getByRole("tablist", { name: "视图切换" })).getByRole("tab", { name: label });
}
const READY_SETTINGS = makeSettings(true, []);
const SUGGESTED_NOTE = {
  source_id: "interview-1",
  source_name: "interviews.md",
  note_path: "notes/interview-1.md",
  source_hash: "b".repeat(64),
  extractor: "MarkdownExtractor",
};

function urlDispatch(routes: Record<string, Promise<Response> | (() => Promise<Response>)>) {
  return (input: string | URL | Request) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    const defaults: Record<string, Promise<Response>> = {
      "/api/notes": emptyNotesResponse(),
      "/api/wiki/entries": emptyWikiResponse(),
    };
    const route = routes[path] ?? defaults[path];
    if (!route) {
      throw new Error(`unexpected fetch: ${url}`);
    }
    // 路由值允许直接给响应或给工厂（如需每次新建的 reject 场景）
    return typeof route === "function" ? route() : route;
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("本地问答界面", () => {
  it("浏览器服务离线时提供准确的手动启动说明和连接检查", async () => {
    let healthAttempts = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
      if (path === "/api/health") {
        healthAttempts += 1;
        if (healthAttempts === 1) {
          throw new Error("service is offline");
        }
        return response({ status: "ok", version: "0.1.0" });
      }
      if (path === "/api/settings") {
        return response(READY_SETTINGS);
      }
      if (path === "/api/notes") {
        return emptyNotesResponse();
      }
      if (path === "/api/wiki/entries") {
        return emptyWikiResponse();
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    const user = userEvent.setup();

    render(<App />);
    const offlineMessage = await screen.findByText(/浏览器页面无法启动本地进程/);
    const offlineStatus = offlineMessage.closest('[role="status"]');
    expect(offlineStatus).not.toBeNull();
    expect(offlineStatus).toHaveTextContent("siku serve --with-ui");
    expect(screen.getByText("服务未连接")).toBeInTheDocument();
    expect(screen.queryByLabelText("基于内容的提问建议")).not.toBeInTheDocument();
    await user.click(viewTab("浏览"));
    expect(screen.getByText("服务未连接")).toBeInTheDocument();
    expect(screen.getByText(/浏览器页面无法启动本地进程/)).toBeInTheDocument();
    await user.click(within(offlineStatus as HTMLElement).getByRole("button", { name: "检查连接" }));
    await waitFor(() => expect(screen.queryByText(/浏览器页面无法启动本地进程/)).not.toBeInTheDocument());
    expect(screen.getByText("服务正常")).toBeInTheDocument();
  });

  it("根据笔记与 wiki 显示提问建议，点击后只预填输入框", async () => {
    let askCalls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
      if (path === "/api/health") return response({ status: "ok", version: "0.1.0" });
      if (path === "/api/settings") return response(READY_SETTINGS);
      if (path === "/api/notes") {
        return response({ notes: [SUGGESTED_NOTE], total: 1, page: 1, page_size: 5 });
      }
      if (path === "/api/notes/interview-1") {
        return response({
          ...SUGGESTED_NOTE,
          anchors: ["用户研究与访谈结论"],
          content: "# 访谈洞察\n\n## 用户研究与访谈结论\n访谈记录。",
        });
      }
      if (path === "/api/wiki/entries") {
        return response({ entries: [{ community_id: 4, title: "社区 0004", generated_at: "now" }] });
      }
      if (path === "/api/wiki/entries/4") {
        return response({
          community_id: 4,
          title: "社区 0004",
          content: "# 社区 0004\n\n## 成员实体\n\n- 本地检索（能力）\n- 向量索引（组件）\n",
          generated_at: "now",
        });
      }
      if (path === "/api/ask") {
        askCalls += 1;
        return response(answer);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    const user = userEvent.setup();

    render(<App />);
    const suggestion = await screen.findByRole("button", {
      name: "《访谈洞察》中「用户研究与访谈结论」的核心内容是什么？",
    });
    expect(suggestion).toHaveAttribute(
      "aria-label",
      "《访谈洞察》中「用户研究与访谈结论」的核心内容是什么？",
    );
    expect(screen.getByRole("button", {
      name: "知识图谱中「本地检索」和「向量索引」有哪些关联？",
    })).toBeInTheDocument();
    await user.click(suggestion);

    const input = screen.getByLabelText("你的问题");
    expect(input).toHaveValue("《访谈洞察》中「用户研究与访谈结论」的核心内容是什么？");
    expect(input).toHaveFocus();
    expect(askCalls).toBe(0);
  });

  it("读取提问建议时显示加载状态", async () => {
    let resolveNotes: ((value: Response) => void) | undefined;
    const pendingNotes = new Promise<Response>((resolve) => {
      resolveNotes = resolve;
    });
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
      if (path === "/api/health") return response({ status: "ok", version: "0.1.0" });
      if (path === "/api/settings") return response(READY_SETTINGS);
      if (path === "/api/notes") return pendingNotes;
      if (path === "/api/wiki/entries") return emptyWikiResponse();
      throw new Error(`unexpected fetch: ${url}`);
    });

    render(<App />);
    expect(await screen.findByText("正在读取推荐问题…")).toBeInTheDocument();
    resolveNotes?.(await response({ notes: [], total: 0, page: 1, page_size: 5 }));
    expect(await screen.findByText("导入资料或生成 wiki 后，会根据已有内容推荐问题。"))
      .toBeInTheDocument();
  });

  it("新资料库没有笔记且 wiki 尚未生成时不展示静态项目示例", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith("/api/health")) return response({ status: "ok", version: "0.1.0" });
      if (url.endsWith("/api/settings")) return response(READY_SETTINGS);
      if (url.includes("/api/notes")) return emptyNotesResponse();
      if (url.endsWith("/api/wiki/entries")) {
        return response(
          { code: "wiki_missing", message: "wiki 尚未生成：请先构建图谱并执行 siku wiki。" },
          false,
        );
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    render(<App />);
    expect(await screen.findByText("导入资料或生成 wiki 后，会根据已有内容推荐问题。"))
      .toBeInTheDocument();
    expect(screen.getByPlaceholderText("输入你想了解的内容")).toBeInTheDocument();
    expect(screen.queryByText(/项目的本地优先边界/)).not.toBeInTheDocument();
  });

  it("推荐来源均读取失败时仍允许用户手动提问", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith("/api/health")) return response({ status: "ok", version: "0.1.0" });
      if (url.endsWith("/api/settings")) return response(READY_SETTINGS);
      if (url.includes("/api/notes") || url.endsWith("/api/wiki/entries")) {
        throw new Error("source unavailable");
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    render(<App />);
    expect(await screen.findByText("暂时无法读取推荐内容，你仍可以直接输入问题。"))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提交问题" })).toBeEnabled();
    expect(screen.getByLabelText("你的问题")).toBeEnabled();
  });

  it("一个推荐来源失败时保留另一个来源生成的建议", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
      if (path === "/api/health") return response({ status: "ok", version: "0.1.0" });
      if (path === "/api/settings") return response(READY_SETTINGS);
      if (path === "/api/notes") throw new Error("notes unavailable");
      if (path === "/api/wiki/entries") {
        return response({ entries: [{ community_id: 6, title: "社区 0006", generated_at: "now" }] });
      }
      if (path === "/api/wiki/entries/6") {
        return response({
          community_id: 6,
          title: "社区 0006",
          content: "# 社区 0006\n\n## 成员实体\n\n- 资料摄取（能力）\n- 内容索引（组件）\n",
          generated_at: "now",
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    render(<App />);
    expect(await screen.findByRole("button", {
      name: "知识图谱中「资料摄取」和「内容索引」有哪些关联？",
    })).toBeInTheDocument();
    expect(screen.queryByText("暂时无法读取推荐内容，你仍可以直接输入问题。"))
      .not.toBeInTheDocument();
  });

  it("问答请求断连时立即更新共享服务状态", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
      if (path === "/api/health") return response({ status: "ok", version: "0.1.0" });
      if (path === "/api/settings") return response(READY_SETTINGS);
      if (path === "/api/notes") return emptyNotesResponse();
      if (path === "/api/wiki/entries") return emptyWikiResponse();
      if (path === "/api/ask") throw new Error("service disconnected");
      throw new Error(`unexpected fetch: ${url}`);
    });
    const user = userEvent.setup();

    render(<App />);
    await user.type(screen.getByLabelText("你的问题"), "连接测试");
    await user.click(screen.getByRole("button", { name: "提交问题" }));
    expect(await screen.findByText("服务未连接")).toBeInTheDocument();
    expect(screen.getByText(/浏览器页面无法启动本地进程/)).toBeInTheDocument();
  });

  it("提交问题后展示回答并可展开引用", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
      if (path === "/api/health") return response({ status: "ok", version: "0.1.0" });
      if (path === "/api/settings") return response(READY_SETTINGS);
      if (path === "/api/notes") return emptyNotesResponse();
      if (path === "/api/wiki/entries") return emptyWikiResponse();
      if (path === "/api/ask") return response(answer);
      throw new Error(`unexpected fetch: ${url}`);
    });
    const user = userEvent.setup();

    render(<App />);
    await user.type(screen.getByLabelText("你的问题"), "边界是什么？");
    await user.click(screen.getByRole("button", { name: "提交问题" }));

    expect(await screen.findByText("内核只通过 localhost HTTP API 暴露能力。")).toBeInTheDocument();
    expect(screen.getByText("architecture.md")).toBeInTheDocument();
    await user.click(screen.getByText("architecture.md"));
    expect(screen.getByText("UI 与内核只通过 localhost HTTP API 通信。")).toBeInTheDocument();
  });

  it("图谱实体联动预填时清掉上一轮回答卡", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
      if (path === "/api/health") {
        return response({ status: "ok", version: "0.1.0" });
      }
      if (path === "/api/settings") {
        return response(READY_SETTINGS);
      }
      if (path === "/api/notes") {
        return emptyNotesResponse();
      }
      if (path === "/api/wiki/entries") {
        return emptyWikiResponse();
      }
      if (path === "/api/ask") {
        return response(answer);
      }
      if (path === "/api/graph/stats") {
        return response({ nodes: 1, edges: 0, communities: 1, types: { 系统: 1 } });
      }
      if (path === "/api/graph/overview") {
        return response({
          nodes: [
            { entity_id: "e-a", name: "Alpha Kernel", type: "系统", degree: 1, community_id: 0 },
          ],
          edges: [],
          truncated: false,
          total_nodes: 1,
          total_edges: 0,
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    const user = userEvent.setup();

    render(<App />);

    // 先完成一轮问答，留下回答卡
    await user.type(screen.getByLabelText("你的问题"), "第一轮问题");
    await user.click(screen.getByRole("button", { name: "提交问题" }));
    expect(await screen.findByRole("heading", { name: "回答" })).toBeInTheDocument();

    // 走图谱联动真实路径：选中实体 → 在问答中查询
    await user.click(viewTab("图谱"));
    await waitFor(() => expect(screen.getByTestId("graph-canvas-stub")).toBeInTheDocument());
    await user.click(screen.getByTestId("graph-canvas-stub"));
    await user.click(screen.getByRole("button", { name: "在问答中查询" }));

    // 新问题已预填、旧回答卡必须被清掉
    const textarea = screen.getByLabelText("你的问题") as HTMLTextAreaElement;
    expect(textarea.value).toBe("请介绍「Alpha Kernel」。");
    expect(screen.queryByRole("heading", { name: "回答" })).not.toBeInTheDocument();
  });

  it("联动预填作废在途旧回答：迟到响应不得上屏", async () => {
    let resolveAsk: (payload: unknown) => void = () => {};
    vi.spyOn(globalThis, "fetch").mockImplementation((input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
      if (path === "/api/health") {
        return response({ status: "ok", version: "0.1.0" });
      }
      if (path === "/api/settings") {
        return response(READY_SETTINGS);
      }
      if (path === "/api/notes") {
        return emptyNotesResponse();
      }
      if (path === "/api/wiki/entries") {
        return emptyWikiResponse();
      }
      if (path === "/api/ask") {
        return new Promise((resolve) => {
          resolveAsk = resolve;
        }) as unknown as Promise<Response>;
      }
      if (path === "/api/graph/stats") {
        return response({ nodes: 1, edges: 0, communities: 1, types: { 系统: 1 } });
      }
      if (path === "/api/graph/overview") {
        return response({
          nodes: [
            { entity_id: "e-a", name: "Alpha Kernel", type: "系统", degree: 1, community_id: 0 },
          ],
          edges: [],
          truncated: false,
          total_nodes: 1,
          total_edges: 0,
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    const user = userEvent.setup();

    render(<App />);

    // 发起提问但让其挂起（受控 Promise 不 resolve）
    await user.type(screen.getByLabelText("你的问题"), "第一轮问题");
    await user.click(screen.getByRole("button", { name: "提交问题" }));
    expect(screen.getByRole("button", { name: "检索与回答中…" })).toBeDisabled();

    // 联动预填：作废在途请求并切回问答视图
    await user.click(viewTab("图谱"));
    await waitFor(() => expect(screen.getByTestId("graph-canvas-stub")).toBeInTheDocument());
    await user.click(screen.getByTestId("graph-canvas-stub"));
    await user.click(screen.getByRole("button", { name: "在问答中查询" }));

    // 迟到的旧回答到达：必须被序号守卫丢弃，不上屏任何回答卡或错误卡
    resolveAsk(answer);
    await user.click(viewTab("图谱"));
    await user.click(viewTab("问答"));
    expect(screen.queryByRole("heading", { name: "回答" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "证据不足" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    const textarea = screen.getByLabelText("你的问题") as HTMLTextAreaElement;
    expect(textarea.value).toBe("请介绍「Alpha Kernel」。");
  });

  it("展示证据不足，不渲染伪造引用", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
      if (path === "/api/health") return response({ status: "ok", version: "0.1.0" });
      if (path === "/api/settings") return response(READY_SETTINGS);
      if (path === "/api/notes") return emptyNotesResponse();
      if (path === "/api/wiki/entries") return emptyWikiResponse();
      if (path === "/api/ask") {
        return response({ ...answer, insufficient_evidence: true, answer: "没有足够证据。", citations: [] });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    const user = userEvent.setup();

    render(<App />);
    await user.type(screen.getByLabelText("你的问题"), "未知问题");
    await user.click(screen.getByRole("button", { name: "提交问题" }));

    expect(await screen.findByRole("heading", { name: "证据不足" })).toBeInTheDocument();
    expect(screen.queryByText("来源依据")).not.toBeInTheDocument();
  });

  it("展示稳定错误并支持重试", async () => {
    let askAttempts = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
      if (path === "/api/health") return response({ status: "ok", version: "0.1.0" });
      if (path === "/api/settings") return response(READY_SETTINGS);
      if (path === "/api/notes") return emptyNotesResponse();
      if (path === "/api/wiki/entries") return emptyWikiResponse();
      if (path === "/api/ask") {
        askAttempts += 1;
        return askAttempts === 1
          ? response({ code: "llm_not_configured", message: "请配置 LLM。" }, false)
          : response(answer);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    const user = userEvent.setup();

    render(<App />);
    await user.type(screen.getByLabelText("你的问题"), "重试问题");
    await user.click(screen.getByRole("button", { name: "提交问题" }));
    expect(await screen.findByText("请配置 LLM。")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试问答" }));
    expect(await screen.findByText("内核只通过 localhost HTTP API 暴露能力。")).toBeInTheDocument();
  });

  it("对格式错误的 API 错误响应使用安全的兜底文案", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
      if (path === "/api/health") return response({ status: "ok", version: "0.1.0" });
      if (path === "/api/settings") return response(READY_SETTINGS);
      if (path === "/api/notes") return emptyNotesResponse();
      if (path === "/api/wiki/entries") return emptyWikiResponse();
      if (path === "/api/ask") return response(null, false);
      throw new Error(`unexpected fetch: ${url}`);
    });
    const user = userEvent.setup();

    render(<App />);
    await user.type(screen.getByLabelText("你的问题"), "异常响应");
    await user.click(screen.getByRole("button", { name: "提交问题" }));

    expect(await screen.findByText("请求失败，请稍后重试。")).toBeInTheDocument();
    expect(screen.getByText("http_error")).toBeInTheDocument();
  });
});

describe("图谱实体联动问答", () => {
  it("选中实体后在问答视图预填问题，不自动发送", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
      expect(path).not.toBe("/api/ask");
        if (path === "/api/health") {
          return response({ status: "ok", version: "0.1.0" });
        }
        if (path === "/api/settings") {
          return response(READY_SETTINGS);
        }
        if (path === "/api/notes") {
          return emptyNotesResponse();
        }
        if (path === "/api/wiki/entries") {
          return emptyWikiResponse();
        }
        if (path === "/api/graph/stats") {
          return response({ nodes: 1, edges: 0, communities: 1, types: { 系统: 1 } });
        }
        if (path === "/api/graph/overview") {
          return response({
            nodes: [
              {
                entity_id: "e-a",
                name: "Alpha Kernel",
                type: "系统",
                degree: 1,
                community_id: 0,
              },
            ],
            edges: [],
            truncated: false,
            total_nodes: 1,
            total_edges: 0,
          });
        }
        throw new Error(`unexpected fetch: ${url}`);
      },
    );
    const user = userEvent.setup();

    render(<App />);
    await user.click(viewTab("图谱"));
    await waitFor(() => expect(screen.getByTestId("graph-canvas-stub")).toBeInTheDocument());

    await user.click(screen.getByTestId("graph-canvas-stub"));
    expect(screen.getByRole("complementary", { name: "实体详情" })).toHaveTextContent("Alpha Kernel");
    await user.click(screen.getByRole("button", { name: "在问答中查询" }));

    const textarea = screen.getByLabelText("你的问题") as HTMLTextAreaElement;
    expect(textarea.value).toBe("请介绍「Alpha Kernel」。");
    // 预填不自动发送：问答仍处空闲态，未触发 /api/ask（mock 内逐请求断言 path != /api/ask）
    expect(screen.getByRole("button", { name: "提交问题" })).toBeInTheDocument();
  });
});

describe("问答就绪门控", () => {
  it("未就绪时置灰提交、列出缺失项并引导去设置", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation(
      urlDispatch({
        "/api/health": response({ status: "ok", version: "0.1.0" }),
        "/api/settings": response(NOT_READY_SETTINGS),
      }),
    );

    render(<App />);
    const submit = await screen.findByRole("button", { name: "提交问题" });
    await waitFor(() => expect(submit).toBeDisabled());
    expect(screen.getByText("问答尚未就绪——模型端点未配置")).toBeInTheDocument();
    expect(
      screen.getByText(/还差：LLM 通道的 API key、embedding 通道的 base_url、embedding 通道的 model。/),
    ).toBeInTheDocument();

    // 输入保持可用：用户可先写问题，Enter 也不触发问答
    await user.type(screen.getByLabelText("你的问题"), "先写好的问题");
    expect(screen.getByLabelText("你的问题")).toHaveValue("先写好的问题");
    await user.type(screen.getByLabelText("你的问题"), "{Enter}");
    expect(screen.queryByRole("button", { name: "检索与回答中…" })).not.toBeInTheDocument();

    // 引导入口直达设置视图
    await user.click(screen.getByRole("button", { name: "去设置" }));
    expect(await screen.findByRole("heading", { name: "模型供给设置" })).toBeInTheDocument();
  });

  it("配置补齐后回到问答视图，提交恢复可用", async () => {
    const user = userEvent.setup();
    let settingsCalls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
      if (path === "/api/health") {
        return response({ status: "ok", version: "0.1.0" });
      }
      if (path === "/api/settings") {
        // 首次（问答视图挂载）未就绪；去设置页再回问答后内核视角已就绪
        settingsCalls += 1;
        return response(settingsCalls === 1 ? NOT_READY_SETTINGS : READY_SETTINGS);
      }
      if (path === "/api/notes") return emptyNotesResponse();
      if (path === "/api/wiki/entries") return emptyWikiResponse();
      throw new Error(`unexpected fetch: ${url}`);
    });

    render(<App />);
    await waitFor(
      () => expect(screen.getByRole("button", { name: "提交问题" })).toBeDisabled(),
    );
    await user.click(screen.getByRole("button", { name: "去设置" }));
    expect(await screen.findByRole("heading", { name: "模型供给设置" })).toBeInTheDocument();
    await user.click(viewTab("问答"));
    await waitFor(
      () => expect(screen.getByRole("button", { name: "提交问题" })).toBeEnabled(),
    );
    expect(screen.queryByText("问答尚未就绪——模型端点未配置")).not.toBeInTheDocument();
  });

  it("保存设置成功后经 PUT 响应立即刷新就绪状态", async () => {
    const user = userEvent.setup();
    let getCalls = 0;
    const readyWrite = { ...READY_SETTINGS, warnings: [], invalid_config_file_overwritten: false };
    vi.spyOn(globalThis, "fetch").mockImplementation(
      ((input: string | URL | Request, init?: RequestInit) => {
        const url =
          typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
        if (path === "/api/health") {
          return response({ status: "ok", version: "0.1.0" });
        }
        if (path === "/api/settings") {
          if (init?.method === "PUT") {
            // 保存响应直接携带最新就绪状态：App 经 onSaved 免二次请求刷新
            return response(readyWrite);
          }
          // GET：App 挂载首查未就绪；保存落盘后（设置页挂载、回问答）均为就绪
          getCalls += 1;
          return response(getCalls === 1 ? NOT_READY_SETTINGS : READY_SETTINGS);
        }
        if (path === "/api/notes") return emptyNotesResponse();
        if (path === "/api/wiki/entries") return emptyWikiResponse();
        throw new Error(`unexpected fetch: ${url}`);
      }) as unknown as typeof fetch,
    );

    render(<App />);
    await waitFor(
      () => expect(screen.getByRole("button", { name: "提交问题" })).toBeDisabled(),
    );
    await user.click(screen.getByRole("button", { name: "去设置" }));
    const llmGroup = await screen.findByRole("group", { name: "LLM 通道" });
    const embedGroup = screen.getByRole("group", { name: "embedding 通道" });
    await user.type(within(llmGroup).getByLabelText("api_key（只写不回显）"), "sk-key");
    await user.type(within(embedGroup).getByLabelText("base_url"), "http://127.0.0.1:11434/v1");
    await user.type(within(embedGroup).getByLabelText("model"), "bge-m3");
    await user.click(screen.getByRole("button", { name: "保存设置" }));
    expect(await screen.findByText("设置已保存，无需重启即可生效。")).toBeInTheDocument();

    await user.click(viewTab("问答"));
    await waitFor(
      () => expect(screen.getByRole("button", { name: "提交问题" })).toBeEnabled(),
    );
    expect(screen.queryByText("问答尚未就绪——模型端点未配置")).not.toBeInTheDocument();
  });

  it("就绪状态获取失败时不锁死提交（fail-open）", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation(
      urlDispatch({
        "/api/health": response({ status: "ok", version: "0.1.0" }),
        "/api/settings": () => Promise.reject(new Error("settings unavailable")),
        "/api/notes": emptyNotesResponse(),
        "/api/wiki/entries": emptyWikiResponse(),
        "/api/ask": response({ code: "model_not_available", message: "端点配置指引。" }, false),
      }),
    );

    render(<App />);
    const submit = await screen.findByRole("button", { name: "提交问题" });
    await waitFor(() => expect(submit).toBeEnabled());
    expect(screen.queryByText("问答尚未就绪——模型端点未配置")).not.toBeInTheDocument();

    // 提交照常发出，失败走既有错误路径展示 API 中文 message
    await user.type(screen.getByLabelText("你的问题"), "照常提交");
    await user.click(submit);
    expect(await screen.findByText("端点配置指引。")).toBeInTheDocument();
  });
});

describe("组件库导航无障碍", () => {
  it("桌面视图导航使用可访问名称并切换当前页面", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith("/api/health")) {
        return response({ status: "ok", version: "0.1.0" });
      }
      if (url.endsWith("/api/settings")) {
        return response(READY_SETTINGS);
      }
      if (url.includes("/api/notes")) {
        return emptyNotesResponse();
      }
      if (url.endsWith("/api/wiki/entries")) {
        return emptyWikiResponse();
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    const user = userEvent.setup();

    render(<App />);
    const nav = screen.getByRole("tablist", { name: "视图切换" });
    expect(within(nav).getAllByRole("tab")).toHaveLength(6);
    expect(viewTab("问答")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "更多视图", hidden: true })).toBeInTheDocument();

    await user.click(viewTab("浏览"));
    expect(viewTab("浏览")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "浏览" })).toBeInTheDocument();
  });

  it("窄屏底部主导航含五个同级视图并保留更多视图入口", async () => {
    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
      matches: query === "(max-width: 40rem)",
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }));
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith("/api/health")) return response({ status: "ok", version: "0.1.0" });
      if (url.endsWith("/api/settings")) return response(READY_SETTINGS);
      if (url.includes("/api/notes")) return emptyNotesResponse();
      if (url.endsWith("/api/wiki/entries")) return emptyWikiResponse();
      throw new Error(`unexpected fetch: ${url}`);
    });
    render(<App />);
    const nav = screen.getByRole("tablist", { name: "视图切换" });
    await waitFor(() => expect(within(nav).getAllByRole("tab")).toHaveLength(5));
    for (const label of ["问答", "浏览", "图谱", "wiki", "资料库"]) {
      expect(within(nav).getByRole("tab", { name: label })).toBeInTheDocument();
    }
    // 设置是低频配置入口：不占底部栏，经更多视图菜单进入
    expect(within(nav).queryByRole("tab", { name: "设置" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "更多视图", hidden: true })).toBeInTheDocument();
  });
});
