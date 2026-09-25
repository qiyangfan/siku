import { cleanup, screen } from "@testing-library/react";
import { render } from "./test-utils";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import type { GraphStats, GraphSubgraph } from "./api";
import { GraphView } from "./GraphView";

// jsdom 无 WebGL：画布以替身组件呈现，画布真实交互由手工冒烟覆盖
vi.mock("./GraphCanvas", () => ({
  GraphCanvas: (props: { selectedId: string | null }) =>
    React.createElement("div", {
      "data-testid": "graph-canvas-stub",
      "data-selected": props.selectedId ?? "",
    }),
}));

const stats: GraphStats = {
  nodes: 2,
  edges: 1,
  communities: 1,
  types: { 概念: 2 },
};

const overview: GraphSubgraph = {
  nodes: [
    { entity_id: "e-a", name: "Alpha Kernel", type: "系统", degree: 1, community_id: 0 },
    { entity_id: "e-b", name: "Beta Module", type: "概念", degree: 1, community_id: 0 },
  ],
  edges: [{ source: "e-a", target: "e-b", type: "相关" }],
  truncated: false,
  total_nodes: 2,
  total_edges: 1,
};

const searchResult = {
  nodes: [{ entity_id: "e-a", name: "Alpha Kernel", type: "系统", degree: 1, community_id: 0 }],
  edges: [],
  truncated: true,
  total_nodes: 2,
  total_edges: 0,
  query: "alpha",
  limit: 20,
};

const neighbors = {
  nodes: [
    { entity_id: "e-a", name: "Alpha Kernel", type: "系统", degree: 1, community_id: 0 },
    { entity_id: "e-b", name: "Beta Module", type: "概念", degree: 1, community_id: 0 },
    { entity_id: "e-c", name: "Alpha Protocol", type: "概念", degree: 2, community_id: 0 },
  ],
  edges: [
    { source: "e-a", target: "e-b", type: "相关" },
    { source: "e-a", target: "e-c", type: "引用" },
  ],
  truncated: true,
  total_nodes: 10,
  total_edges: 12,
};

function jsonResponse(payload: unknown, ok = true) {
  return Promise.resolve({ ok, json: () => Promise.resolve(payload) } as Response);
}

type RouteTable = Record<string, (url: string) => ReturnType<typeof jsonResponse>>;

function mockFetchByRoutes(routes: RouteTable) {
  vi.spyOn(globalThis, "fetch").mockImplementation((input: string | URL | Request) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    const route = routes[path.split("?")[0]];
    if (route === undefined) {
      throw new Error(`unexpected fetch: ${url}`);
    }
    return route(path);
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("图谱视图", () => {
  it("加载聚合统计与概览画布", async () => {
    mockFetchByRoutes({
      "/api/graph/stats": () => jsonResponse(stats),
      "/api/graph/overview": () => jsonResponse(overview),
    });

    render(<GraphView onAskEntity={vi.fn()} />);
    expect(await screen.findByTestId("graph-canvas-stub")).toBeInTheDocument();
    expect(screen.getByText(/全图 2 个实体、1 条关系，1 个社区/)).toBeInTheDocument();
  });

  it("搜索实体并展开邻域：截断提示与联动面板", async () => {
    mockFetchByRoutes({
      "/api/graph/stats": () => jsonResponse(stats),
      "/api/graph/overview": () => jsonResponse(overview),
      "/api/graph/search": () => jsonResponse(searchResult),
      "/api/graph/neighbors/e-a": (url) => {
        expect(url).toContain("limit=50");
        expect(url).toContain("depth=1");
        return jsonResponse(neighbors);
      },
    });
    const user = userEvent.setup();

    render(<GraphView onAskEntity={vi.fn()} />);
    await screen.findByTestId("graph-canvas-stub");

    await user.type(screen.getByLabelText("搜索实体"), "alpha");
    await user.click(screen.getByRole("button", { name: "搜索" }));

    // 搜索截断数上屏：服务端 truncated + total_nodes 必须可见
    expect(
      await screen.findByText(/显示前 1 个：（命中过多已截断/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Alpha Kernel" }));
    const panel = await screen.findByRole("complementary", { name: "实体详情" });
    expect(panel).toHaveTextContent("Alpha Kernel");
    expect(panel).toHaveTextContent("系统");

    await user.click(screen.getByRole("button", { name: "展开邻域" }));
    expect(await screen.findByRole("button", { name: "邻域已展开" })).toBeInTheDocument();
    expect(screen.getByText(/已截断：当前展示 3 \/ 全图 10 个实体/)).toBeInTheDocument();
  });

  it("实体可联动问答预填，不自动发送", async () => {
    mockFetchByRoutes({
      "/api/graph/stats": () => jsonResponse(stats),
      "/api/graph/overview": () => jsonResponse(overview),
      "/api/graph/search": () => jsonResponse(searchResult),
    });
    const onAskEntity = vi.fn();
    const user = userEvent.setup();

    render(<GraphView onAskEntity={onAskEntity} />);
    await screen.findByTestId("graph-canvas-stub");

    await user.type(screen.getByLabelText("搜索实体"), "alpha");
    await user.click(screen.getByRole("button", { name: "搜索" }));
    await user.click(await screen.findByRole("button", { name: "Alpha Kernel" }));
    await user.click(screen.getByRole("button", { name: "在问答中查询" }));

    expect(onAskEntity).toHaveBeenCalledWith("Alpha Kernel");
  });

  it("图谱未构建时空态提供构建入口，成功后自动加载画布", async () => {
    const buildReport = {
      chunks: 2,
      nodes: 2,
      edges: 1,
      communities: 1,
      ambiguous_entities: 0,
      cache_hits: 0,
      llm_calls: 3,
      warnings: [],
      empty_corpus: false,
      extractor: { id: "llm-graph", model: "qwen-plus", prompt_version: "v1" },
    };
    let statsCalls = 0;
    const user = userEvent.setup();
    mockFetchByRoutes({
      "/api/graph/stats": () => {
        statsCalls += 1;
        return statsCalls === 1
          ? jsonResponse({ code: "graph_missing", message: "图谱尚未构建。" }, false)
          : jsonResponse(stats);
      },
      "/api/graph/overview": () => jsonResponse(overview),
      "/api/graph": () => jsonResponse(buildReport),
    });

    render(<GraphView onAskEntity={vi.fn()} />);
    expect(await screen.findByText("图谱尚未构建")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "构建图谱" }));
    expect(await screen.findByTestId("graph-canvas-stub")).toBeInTheDocument();
    expect(
      screen.getByText(/图谱已构建：2 个实体、1 条关系、1 个社区（LLM 调用 3 次）/),
    ).toBeInTheDocument();
  });

  it("语料为空时构建如实反馈并刷新为空图谱", async () => {
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
    const emptyStats: GraphStats = { nodes: 0, edges: 0, communities: 0, types: {} };
    const emptyOverview = {
      nodes: [],
      edges: [],
      truncated: false,
      total_nodes: 0,
      total_edges: 0,
    };
    let statsCalls = 0;
    const user = userEvent.setup();
    mockFetchByRoutes({
      "/api/graph/stats": () => {
        statsCalls += 1;
        // 构建前产物缺失（404），空语料构建后落了空产物（200 零值）
        return statsCalls === 1
          ? jsonResponse({ code: "graph_missing", message: "图谱尚未构建。" }, false)
          : jsonResponse(emptyStats);
      },
      "/api/graph/overview": () => jsonResponse(emptyOverview),
      "/api/graph": () => jsonResponse(buildReport),
    });

    render(<GraphView onAskEntity={vi.fn()} />);
    expect(await screen.findByText("图谱尚未构建")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "构建图谱" }));
    // 空语料同样落空产物：视图必须刷新到与磁盘一致（空画布），不得残留空态卡
    expect(await screen.findByTestId("graph-canvas-stub")).toBeInTheDocument();
    expect(screen.getByText(/全图 0 个实体、0 条关系/)).toBeInTheDocument();
    expect(
      screen.getByText(/语料为空：图谱为空、无可展示内容；请先在「资料库」导入笔记。/),
    ).toBeInTheDocument();
  });

  it("空态构建失败时展示后端中文信息并恢复按钮", async () => {
    const user = userEvent.setup();
    mockFetchByRoutes({
      "/api/graph/stats": () =>
        jsonResponse({ code: "graph_missing", message: "图谱尚未构建。" }, false),
      "/api/graph/overview": () => jsonResponse(overview),
      "/api/graph": () =>
        jsonResponse(
          { code: "llm_not_configured", message: "尚未配置 LLM API key，请在设置中补全。" },
          false,
        ),
    });

    render(<GraphView onAskEntity={vi.fn()} />);
    expect(await screen.findByText("图谱尚未构建")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "构建图谱" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("尚未配置 LLM API key");
    expect(screen.getByRole("button", { name: "构建图谱" })).toBeEnabled();
  });

  it("已建态可更新图谱：幂等缓存路径并在完成后刷新状态行", async () => {
    const buildReport = {
      chunks: 2,
      nodes: 2,
      edges: 1,
      communities: 1,
      ambiguous_entities: 0,
      cache_hits: 5,
      llm_calls: 0,
      warnings: [],
      empty_corpus: false,
      extractor: { id: "llm-graph", model: "qwen-plus", prompt_version: "v1" },
    };
    const user = userEvent.setup();
    mockFetchByRoutes({
      "/api/graph/stats": () => jsonResponse(stats),
      "/api/graph/overview": () => jsonResponse(overview),
      "/api/graph": () => jsonResponse(buildReport),
    });

    render(<GraphView onAskEntity={vi.fn()} />);
    await screen.findByTestId("graph-canvas-stub");

    await user.click(screen.getByRole("button", { name: "更新图谱" }));
    expect(
      await screen.findByText(/图谱已构建：2 个实体、1 条关系、1 个社区（LLM 调用 0 次）/),
    ).toBeInTheDocument();
  });

  it("已建态更新图谱失败时展示后端中文信息并恢复按钮", async () => {
    const user = userEvent.setup();
    mockFetchByRoutes({
      "/api/graph/stats": () => jsonResponse(stats),
      "/api/graph/overview": () => jsonResponse(overview),
      "/api/graph": () =>
        jsonResponse(
          { code: "llm_not_configured", message: "尚未配置 LLM API key，请在设置中补全。" },
          false,
        ),
    });

    render(<GraphView onAskEntity={vi.fn()} />);
    await screen.findByTestId("graph-canvas-stub");

    await user.click(screen.getByRole("button", { name: "更新图谱" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("尚未配置 LLM API key");
    expect(screen.getByRole("button", { name: "更新图谱" })).toBeEnabled();
    expect(screen.getByTestId("graph-canvas-stub")).toBeInTheDocument();
  });

  it("已建态更新成功但刷新失败时展示告警卡且画布保留", async () => {
    let statsCalls = 0;
    const user = userEvent.setup();
    mockFetchByRoutes({
      "/api/graph/stats": () => {
        statsCalls += 1;
        return statsCalls === 1
          ? jsonResponse(stats)
          : jsonResponse({ code: "internal_error", message: "服务内部错误。" }, false);
      },
      "/api/graph/overview": () => jsonResponse(overview),
      "/api/graph": () =>
        jsonResponse({
          chunks: 2,
          nodes: 2,
          edges: 1,
          communities: 1,
          ambiguous_entities: 0,
          cache_hits: 5,
          llm_calls: 0,
          warnings: [],
          empty_corpus: false,
          extractor: { id: "llm-graph", model: "qwen-plus", prompt_version: "v1" },
        }),
    });

    render(<GraphView onAskEntity={vi.fn()} />);
    await screen.findByTestId("graph-canvas-stub");

    await user.click(screen.getByRole("button", { name: "更新图谱" }));
    expect(await screen.findByText("图谱刷新失败")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试读取" })).toBeInTheDocument();
    // 画布保留：刷新失败不得清空已建态
    expect(screen.getByTestId("graph-canvas-stub")).toBeInTheDocument();
  });

  it("空态构建成功但刷新失败时同时展示构建结果与读取告警", async () => {
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
    let statsCalls = 0;
    const user = userEvent.setup();
    mockFetchByRoutes({
      "/api/graph/stats": () => {
        statsCalls += 1;
        return statsCalls === 1
          ? jsonResponse({ code: "graph_missing", message: "图谱尚未构建。" }, false)
          : jsonResponse({ code: "internal_error", message: "服务内部错误。" }, false);
      },
      "/api/graph/overview": () => jsonResponse(overview),
      "/api/graph": () => jsonResponse(buildReport),
    });

    render(<GraphView onAskEntity={vi.fn()} />);
    expect(await screen.findByText("图谱尚未构建")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "构建图谱" }));
    // 构建成功 note 与刷新失败告警必须同屏可见，不得互相覆盖
    expect(
      await screen.findByText(/语料为空：图谱为空、无可展示内容；请先在「资料库」导入笔记。/),
    ).toBeInTheDocument();
    expect(screen.getByText("服务内部错误。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试读取" })).toBeInTheDocument();
  });
});
