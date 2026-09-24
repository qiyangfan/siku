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
    expect(screen.getByRole("button", { name: "重新生成 wiki" })).toBeInTheDocument();
  });

  it("空态点击「生成 wiki」成功后自动刷新清单", async () => {
    const generateReport = { entries: 2, cache_hits: 0, llm_calls: 4, empty_graph: false };
    let entriesCalls = 0;
    const user = userEvent.setup();
    mockFetchByRoutes({
      "/api/wiki/entries": () => {
        entriesCalls += 1;
        return entriesCalls === 1
          ? jsonResponse({ code: "wiki_missing", message: "wiki 尚未生成。" }, false)
          : jsonResponse(entries);
      },
      "/api/wiki": () => jsonResponse(generateReport),
    });

    render(<WikiView />);
    expect(await screen.findByText("wiki 尚未生成")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "生成 wiki" }));
    expect(
      await screen.findByText("共 2 个社区条目；内容由模型基于语料生成。"),
    ).toBeInTheDocument();
    expect(screen.getByText(/wiki 已生成：2 个条目（LLM 调用 4 次）/)).toBeInTheDocument();
  });

  it("生成遇图谱缺失时就地引导构建，构建成功后自动续跑生成", async () => {
    const buildReport = {
      chunks: 2,
      nodes: 3,
      edges: 2,
      communities: 1,
      ambiguous_entities: 0,
      cache_hits: 0,
      llm_calls: 2,
      warnings: [],
      empty_corpus: false,
      extractor: { id: "llm-graph", model: "qwen-plus", prompt_version: "v1" },
    };
    const generateReport = { entries: 2, cache_hits: 0, llm_calls: 4, empty_graph: false };
    let wikiCalls = 0;
    let entriesCalls = 0;
    const user = userEvent.setup();
    mockFetchByRoutes({
      "/api/wiki/entries": () => {
        entriesCalls += 1;
        return entriesCalls === 1
          ? jsonResponse({ code: "wiki_missing", message: "wiki 尚未生成。" }, false)
          : jsonResponse(entries);
      },
      "/api/wiki": () => {
        wikiCalls += 1;
        return wikiCalls === 1
          ? jsonResponse({ code: "graph_artifacts_missing", message: "图谱产物缺失。" }, false)
          : jsonResponse(generateReport);
      },
      "/api/graph": () => jsonResponse(buildReport),
    });

    render(<WikiView />);
    expect(await screen.findByText("wiki 尚未生成")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "生成 wiki" }));
    expect(await screen.findByRole("button", { name: "构建图谱" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "构建图谱" }));
    expect(
      await screen.findByText("共 2 个社区条目；内容由模型基于语料生成。"),
    ).toBeInTheDocument();
    expect(wikiCalls).toBe(2);
  });

  it("已建态重新生成 wiki：成功后刷新清单并清空旧选中条目", async () => {
    const generateReport = { entries: 2, cache_hits: 2, llm_calls: 0, empty_graph: false };
    const user = userEvent.setup();
    mockFetchByRoutes({
      "/api/wiki/entries": () => jsonResponse(entries),
      "/api/wiki/entries/1": () => jsonResponse(entryDetail),
      "/api/wiki": () => jsonResponse(generateReport),
    });

    render(<WikiView />);
    await user.click(await screen.findByRole("button", { name: /社区 0001/ }));
    expect(await screen.findByRole("heading", { level: 3, name: "社区 0001" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重新生成 wiki" }));
    expect(
      await screen.findByText(/wiki 已生成：2 个条目（LLM 调用 0 次）/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 3, name: "社区 0001" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("从左侧选择一个条目")).toBeInTheDocument();
  });

  it("已建态重新生成遇图谱缺失时展示引导反馈", async () => {
    const user = userEvent.setup();
    mockFetchByRoutes({
      "/api/wiki/entries": () => jsonResponse(entries),
      "/api/wiki": () =>
        jsonResponse(
          { code: "graph_artifacts_missing", message: "图谱产物缺失。" },
          false,
        ),
    });

    render(<WikiView />);
    expect(
      await screen.findByText("共 2 个社区条目；内容由模型基于语料生成。"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重新生成 wiki" }));
    // 已建态下 graphMissingKnown 不驱动卡片切换，必须显式给出可见反馈（禁静默失败）
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "图谱产物缺失：请先在「图谱」视图构建图谱，再重新生成 wiki。",
    );
    expect(screen.getByRole("button", { name: "重新生成 wiki" })).toBeEnabled();
  });

  it("两段式构建成功但零社区时清除缺失旗标并如实反馈", async () => {
    const buildReport = {
      chunks: 2,
      nodes: 2,
      edges: 1,
      communities: 0,
      ambiguous_entities: 0,
      cache_hits: 0,
      llm_calls: 2,
      warnings: ["实体抽取全部为空"],
      empty_corpus: false,
      extractor: { id: "llm-graph", model: "qwen-plus", prompt_version: "v1" },
    };
    let wikiCalls = 0;
    const user = userEvent.setup();
    mockFetchByRoutes({
      "/api/wiki/entries": () =>
        jsonResponse({ code: "wiki_missing", message: "wiki 尚未生成。" }, false),
      "/api/wiki": () => {
        wikiCalls += 1;
        return wikiCalls === 1
          ? jsonResponse({ code: "graph_artifacts_missing", message: "图谱产物缺失。" }, false)
          : jsonResponse({ entries: 0, cache_hits: 0, llm_calls: 0, empty_graph: true });
      },
      "/api/graph": () => jsonResponse(buildReport),
    });

    render(<WikiView />);
    expect(await screen.findByText("wiki 尚未生成")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "生成 wiki" }));
    await user.click(await screen.findByRole("button", { name: "构建图谱" }));
    // 200 empty_graph 证明图谱产物已存在：缺失旗标必须清除，不得残留矛盾引导
    expect(await screen.findByText(/图谱中没有可摘要的社区，未产出 wiki 条目。/)).toBeInTheDocument();
    expect(
      screen.getByText(/wiki 由图谱社区摘要生成，使用「设置」中配置的 LLM 通道；生成可能需要几分钟。/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/而图谱尚未构建/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "生成 wiki" })).toBeInTheDocument();
  });

  it("两段式构建遇空语料时停在引导并不续跑生成", async () => {
    const buildReport = {
      chunks: 0,
      nodes: 0,
      edges: 0,
      communities: 0,
      ambiguous_entities: 0,
      cache_hits: 0,
      llm_calls: 0,
      warnings: [],
      empty_corpus: true,
      extractor: { id: "llm-graph", model: "qwen-plus", prompt_version: "v1" },
    };
    let wikiCalls = 0;
    const user = userEvent.setup();
    mockFetchByRoutes({
      "/api/wiki/entries": () =>
        jsonResponse({ code: "wiki_missing", message: "wiki 尚未生成。" }, false),
      "/api/wiki": () => {
        wikiCalls += 1;
        return jsonResponse(
          { code: "graph_artifacts_missing", message: "图谱产物缺失。" },
          false,
        );
      },
      "/api/graph": () => jsonResponse(buildReport),
    });

    render(<WikiView />);
    expect(await screen.findByText("wiki 尚未生成")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "生成 wiki" }));
    await user.click(await screen.findByRole("button", { name: "构建图谱" }));
    // 空语料继续生成只会得到 empty_graph：应停在可行动的导入引导上
    expect(
      await screen.findByText(/语料为空：图谱为空、无可生成内容；请先在「资料库」导入笔记。/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "构建图谱" })).toBeInTheDocument();
    expect(wikiCalls).toBe(1);
  });

  it("已建态重新生成遇 LLM 未配置时展示后端中文信息并恢复按钮", async () => {
    const user = userEvent.setup();
    mockFetchByRoutes({
      "/api/wiki/entries": () => jsonResponse(entries),
      "/api/wiki": () =>
        jsonResponse(
          { code: "llm_not_configured", message: "尚未配置 LLM API key，请在设置中补全。" },
          false,
        ),
    });

    render(<WikiView />);
    expect(
      await screen.findByText("共 2 个社区条目；内容由模型基于语料生成。"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重新生成 wiki" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("尚未配置 LLM API key");
    expect(screen.getByRole("button", { name: "重新生成 wiki" })).toBeEnabled();
    // 清单保留：失败不得清空已建态
    expect(screen.getByRole("button", { name: /社区 0001/ })).toBeInTheDocument();
  });

  it("已建态重新生成成功但清单刷新失败时展示告警卡且清单保留", async () => {
    const generateReport = { entries: 2, cache_hits: 2, llm_calls: 0, empty_graph: false };
    let entriesCalls = 0;
    const user = userEvent.setup();
    mockFetchByRoutes({
      "/api/wiki/entries": () => {
        entriesCalls += 1;
        return entriesCalls === 1
          ? jsonResponse(entries)
          : jsonResponse({ code: "internal_error", message: "服务内部错误。" }, false);
      },
      "/api/wiki": () => jsonResponse(generateReport),
    });

    render(<WikiView />);
    expect(
      await screen.findByText("共 2 个社区条目；内容由模型基于语料生成。"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重新生成 wiki" }));
    expect(await screen.findByText("wiki 清单刷新失败")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试读取" })).toBeInTheDocument();
    // 旧清单保留 + 成功 note 同屏：刷新失败不得清空已建态
    expect(screen.getByText(/wiki 已生成：2 个条目（LLM 调用 0 次）/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /社区 0001/ })).toBeInTheDocument();
  });

  it("空态生成失败时展示后端中文信息并恢复按钮", async () => {
    const user = userEvent.setup();
    mockFetchByRoutes({
      "/api/wiki/entries": () =>
        jsonResponse({ code: "wiki_missing", message: "wiki 尚未生成。" }, false),
      "/api/wiki": () =>
        jsonResponse(
          { code: "llm_not_configured", message: "尚未配置 LLM API key，请在设置中补全。" },
          false,
        ),
    });

    render(<WikiView />);
    expect(await screen.findByText("wiki 尚未生成")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "生成 wiki" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("尚未配置 LLM API key");
    expect(screen.getByRole("button", { name: "生成 wiki" })).toBeEnabled();
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
