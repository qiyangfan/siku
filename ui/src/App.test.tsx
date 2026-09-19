import { cleanup, render, screen, waitFor } from "@testing-library/react";
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

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("本地问答界面", () => {
  it("提交问题后展示回答并可展开引用", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response({ status: "ok", version: "0.1.0" }))
      .mockImplementationOnce(() => response(answer));
    const user = userEvent.setup();

    render(<App />);
    await waitFor(() => expect(screen.getByText("内核已连接")).toBeInTheDocument());
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
    await waitFor(() => expect(screen.getByText("内核已连接")).toBeInTheDocument());

    // 先完成一轮问答，留下回答卡
    await user.type(screen.getByLabelText("你的问题"), "第一轮问题");
    await user.click(screen.getByRole("button", { name: "提交问题" }));
    expect(await screen.findByRole("heading", { name: "回答" })).toBeInTheDocument();

    // 走图谱联动真实路径：选中实体 → 在问答中查询
    await user.click(screen.getByRole("button", { name: "图谱" }));
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
    await waitFor(() => expect(screen.getByText("内核已连接")).toBeInTheDocument());

    // 发起提问但让其挂起（受控 Promise 不 resolve）
    await user.type(screen.getByLabelText("你的问题"), "第一轮问题");
    await user.click(screen.getByRole("button", { name: "提交问题" }));
    expect(screen.getByRole("button", { name: "检索与回答中…" })).toBeDisabled();

    // 联动预填：作废在途请求并切回问答视图
    await user.click(screen.getByRole("button", { name: "图谱" }));
    await waitFor(() => expect(screen.getByTestId("graph-canvas-stub")).toBeInTheDocument());
    await user.click(screen.getByTestId("graph-canvas-stub"));
    await user.click(screen.getByRole("button", { name: "在问答中查询" }));

    // 迟到的旧回答到达：必须被序号守卫丢弃，不上屏任何回答卡或错误卡
    resolveAsk(answer);
    await user.click(screen.getByRole("button", { name: "图谱" }));
    await user.click(screen.getByRole("button", { name: "问答" }));
    expect(screen.queryByRole("heading", { name: "回答" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "证据不足" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    const textarea = screen.getByLabelText("你的问题") as HTMLTextAreaElement;
    expect(textarea.value).toBe("请介绍「Alpha Kernel」。");
  });

  it("展示证据不足，不渲染伪造引用", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response({ status: "ok", version: "0.1.0" }))
      .mockImplementationOnce(() =>
        response({ ...answer, insufficient_evidence: true, answer: "没有足够证据。", citations: [] }),
      );
    const user = userEvent.setup();

    render(<App />);
    await waitFor(() => expect(screen.getByText("内核已连接")).toBeInTheDocument());
    await user.type(screen.getByLabelText("你的问题"), "未知问题");
    await user.click(screen.getByRole("button", { name: "提交问题" }));

    expect(await screen.findByRole("heading", { name: "证据不足" })).toBeInTheDocument();
    expect(screen.queryByText("来源依据")).not.toBeInTheDocument();
  });

  it("展示稳定错误并支持重试", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response({ status: "ok", version: "0.1.0" }))
      .mockImplementationOnce(() => response({ code: "llm_not_configured", message: "请配置 LLM。" }, false))
      .mockImplementationOnce(() => response(answer));
    const user = userEvent.setup();

    render(<App />);
    await waitFor(() => expect(screen.getByText("内核已连接")).toBeInTheDocument());
    await user.type(screen.getByLabelText("你的问题"), "重试问题");
    await user.click(screen.getByRole("button", { name: "提交问题" }));
    expect(await screen.findByText("请配置 LLM。")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试问答" }));
    expect(await screen.findByText("内核只通过 localhost HTTP API 暴露能力。")).toBeInTheDocument();
  });

  it("对格式错误的 API 错误响应使用安全的兜底文案", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockImplementationOnce(() => response({ status: "ok", version: "0.1.0" }))
      .mockImplementationOnce(() => response(null, false));
    const user = userEvent.setup();

    render(<App />);
    await waitFor(() => expect(screen.getByText("内核已连接")).toBeInTheDocument());
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
    await waitFor(() => expect(screen.getByText("内核已连接")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "图谱" }));
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
