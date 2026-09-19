import { cleanup, render, screen } from "@testing-library/react";
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

  it("图谱未构建时给出可行动的空态提示", async () => {
    mockFetchByRoutes({
      "/api/graph/stats": () =>
        jsonResponse({ code: "graph_missing", message: "图谱尚未构建。" }, false),
      "/api/graph/overview": () => jsonResponse(overview),
    });

    render(<GraphView onAskEntity={vi.fn()} />);
    expect(await screen.findByText("图谱尚未构建")).toBeInTheDocument();
    expect(screen.getByText(/siku graph/)).toBeInTheDocument();
  });
});
