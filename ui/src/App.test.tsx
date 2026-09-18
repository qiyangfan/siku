import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

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
