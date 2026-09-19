import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getGraphNeighbors,
  getGraphOverview,
  getGraphStats,
  searchGraphEntities,
  type ApiError,
  type GraphEdge,
  type GraphNode,
  type GraphStats,
  type GraphSubgraph,
} from "./api";
import { GraphCanvas } from "./GraphCanvas";

const OVERVIEW_LIMIT = 200;
const NEIGHBOR_LIMIT = 50;
const SEARCH_LIMIT = 20;
const NEIGHBOR_DEPTH = 1;

function isApiError(error: unknown): error is ApiError {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    typeof error.code === "string" &&
    "message" in error &&
    typeof error.message === "string"
  );
}

function connectionFallback(caught: unknown): string {
  return isApiError(caught)
    ? caught.message
    : "无法连接本地内核，请确认 siku serve 已启动。";
}

type GraphModel = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  totalNodes: number;
  totalEdges: number;
};

/** 把邻域展开结果并入当前画布模型：节点/边取并集，候选总数取较大值。 */
function mergeSubgraph(model: GraphModel, subgraph: GraphSubgraph): GraphModel {
  const nodeIds = new Set(model.nodes.map((node) => node.entity_id));
  const edgeKeys = new Set(model.edges.map((edge) => `${edge.source}\u0000${edge.target}\u0000${edge.type}`));
  const nodes = [...model.nodes];
  for (const node of subgraph.nodes) {
    if (!nodeIds.has(node.entity_id)) {
      nodeIds.add(node.entity_id);
      nodes.push(node);
    }
  }
  const edges = [...model.edges];
  for (const edge of subgraph.edges) {
    const key = `${edge.source}\u0000${edge.target}\u0000${edge.type}`;
    if (!edgeKeys.has(key)) {
      edgeKeys.add(key);
      edges.push(edge);
    }
  }
  return {
    nodes,
    edges,
    totalNodes: Math.max(model.totalNodes, subgraph.total_nodes),
    totalEdges: Math.max(model.totalEdges, subgraph.total_edges),
  };
}

export function GraphView({ onAskEntity }: { onAskEntity: (name: string) => void }) {
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [model, setModel] = useState<GraphModel | null>(null);
  const [missing, setMissing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<GraphNode[] | null>(null);
  const [searchTruncated, setSearchTruncated] = useState(false);
  const [searchTotal, setSearchTotal] = useState(0);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [expanding, setExpanding] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  // 各异步操作独立序号防竞态：慢响应不得覆盖同类新操作；
  // 跨操作不共用序号，避免被否决方的 loading 旗标永久卡死
  const loadSeqRef = useRef(0);
  const searchSeqRef = useRef(0);
  const expandSeqRef = useRef(0);

  const loadGraph = useCallback(async () => {
    const seq = ++loadSeqRef.current;
    try {
      const [nextStats, overview] = await Promise.all([
        getGraphStats(),
        getGraphOverview(OVERVIEW_LIMIT),
      ]);
      if (seq !== loadSeqRef.current) {
        return;
      }
      setStats(nextStats);
      setModel({
        nodes: overview.nodes,
        edges: overview.edges,
        totalNodes: overview.total_nodes,
        totalEdges: overview.total_edges,
      });
      setMissing(false);
      setLoadError(null);
    } catch (caught: unknown) {
      if (seq !== loadSeqRef.current) {
        return;
      }
      if (isApiError(caught) && caught.code === "graph_missing") {
        setMissing(true);
      } else {
        setLoadError(connectionFallback(caught));
      }
    }
  }, []);

  useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  const runSearch = useCallback(async () => {
    const query = searchQuery.trim();
    if (!query) {
      return;
    }
    const seq = ++searchSeqRef.current;
    setSearching(true);
    setActionError(null);
    try {
      const result = await searchGraphEntities(query, SEARCH_LIMIT);
      if (seq !== searchSeqRef.current) {
        return;
      }
      setSearchResults(result.nodes);
      setSearchTruncated(result.truncated);
      setSearchTotal(result.total_nodes);
    } catch (caught: unknown) {
      if (seq !== searchSeqRef.current) {
        return;
      }
      setActionError(connectionFallback(caught));
    } finally {
      if (seq === searchSeqRef.current) {
        setSearching(false);
      }
    }
  }, [searchQuery]);

  const expandNeighborhood = useCallback(
    async (node: GraphNode) => {
      if (model === null) {
        return;
      }
      const seq = ++expandSeqRef.current;
      setExpanding(true);
      setActionError(null);
      try {
        const subgraph = await getGraphNeighbors(node.entity_id, NEIGHBOR_LIMIT, NEIGHBOR_DEPTH);
        if (seq !== expandSeqRef.current) {
          return;
        }
        setModel((current) => (current === null ? current : mergeSubgraph(current, subgraph)));
        setExpanded((current) => new Set(current).add(node.entity_id));
      } catch (caught: unknown) {
        if (seq !== expandSeqRef.current) {
          return;
        }
        setActionError(connectionFallback(caught));
      } finally {
        if (seq === expandSeqRef.current) {
          setExpanding(false);
        }
      }
    },
    [model],
  );

  const truncated = model !== null && model.nodes.length < model.totalNodes;

  const communityLegend = useMemo(() => {
    if (stats === null || stats.communities === 0) {
      return null;
    }
    return `${stats.communities} 个社区（颜色区分）`;
  }, [stats]);

  if (missing) {
    return (
      <section className="graph-view" aria-labelledby="graph-title">
        <GraphHeader />
        <div className="library-empty" role="note">
          <strong>图谱尚未构建</strong>
          <p>图谱由笔记投影抽取实体与关系生成；请先在终端执行 <code>siku graph</code>，完成后回到本视图。</p>
        </div>
      </section>
    );
  }

  if (loadError !== null && model === null) {
    return (
      <div className="status-card status-error" role="alert">
        <div>
          <strong>图谱读取失败</strong>
          <p>{loadError}</p>
        </div>
        <button
          type="button"
          className="button-secondary"
          onClick={() => void loadGraph()}
        >
          重试读取
        </button>
      </div>
    );
  }

  if (model === null) {
    return (
      <div className="settings-loading" role="status" aria-live="polite">
        正在加载图谱…
      </div>
    );
  }

  return (
    <section className="graph-view" aria-labelledby="graph-title">
      <GraphHeader />
      <p className="hint">
        {stats !== null
          ? `全图 ${stats.nodes} 个实体、${stats.edges} 条关系${communityLegend !== null ? `，${communityLegend}` : ""}。`
          : "画布展示度数最高的实体子集；搜索并展开邻域以探索更多。"}
      </p>

      <div className="graph-controls">
        <form
          className="graph-search"
          onSubmit={(event) => {
            event.preventDefault();
            void runSearch();
          }}
        >
          <label className="visually-hidden" htmlFor="graph-search-input">
            搜索实体
          </label>
          <input
            id="graph-search-input"
            type="text"
            value={searchQuery}
            placeholder="按实体名搜索…"
            onChange={(event) => setSearchQuery(event.target.value)}
          />
          <button type="submit" disabled={searching || searchQuery.trim() === ""}>
            {searching ? "搜索中…" : "搜索"}
          </button>
        </form>
        {truncated && (
          <p className="graph-truncated" role="status">
            已截断：当前展示 {model.nodes.length} / 全图 {model.totalNodes} 个实体。
          </p>
        )}
      </div>

      {actionError !== null && (
        <p className="message message-error" role="alert">
          {actionError}
        </p>
      )}

      {searchResults !== null && searchResults.length > 0 && (
        <div className="graph-search-results" aria-label="搜索结果">
          <p className="hint" role="status">
            命中 {searchTotal} 个实体，显示前 {searchResults.length} 个：
            {searchTruncated && "（命中过多已截断，请细化关键词）"}
          </p>
          <div className="graph-search-chips">
            {searchResults.map((node) => (
              <button
                key={node.entity_id}
                type="button"
                className={
                  selected?.entity_id === node.entity_id
                    ? "graph-chip graph-chip-active"
                    : "graph-chip"
                }
                onClick={() => setSelected(node)}
              >
                {node.name}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="graph-stage">
        <GraphCanvas
          nodes={model.nodes}
          edges={model.edges}
          selectedId={selected?.entity_id ?? null}
          onSelect={setSelected}
        />
        {selected !== null && (
          <aside className="graph-panel" aria-label="实体详情">
            <h3>{selected.name}</h3>
            <dl className="graph-panel-meta">
              <div>
                <dt>类型</dt>
                <dd>{selected.type}</dd>
              </div>
              <div>
                <dt>度数</dt>
                <dd>{selected.degree}</dd>
              </div>
              <div>
                <dt>社区</dt>
                <dd>{selected.community_id === null ? "未分配" : `#${selected.community_id}`}</dd>
              </div>
            </dl>
            <div className="graph-panel-actions">
              <button
                type="button"
                disabled={expanding || expanded.has(selected.entity_id)}
                onClick={() => void expandNeighborhood(selected)}
              >
                {expanded.has(selected.entity_id)
                  ? "邻域已展开"
                  : expanding
                    ? "展开中…"
                    : "展开邻域"}
              </button>
              <button type="button" className="button-secondary" onClick={() => onAskEntity(selected.name)}>
                在问答中查询
              </button>
            </div>
          </aside>
        )}
      </div>
    </section>
  );
}

function GraphHeader() {
  return (
    <div className="graph-header">
      <div>
        <h2 id="graph-title">图谱</h2>
        <p className="hint">实体关系只读画布；点击节点查看详情，服务端保证查询有界。</p>
      </div>
    </div>
  );
}

export default GraphView;
