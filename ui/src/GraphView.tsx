import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Alert, Button, Group, Loader, Paper, Stack, TextInput } from "@mantine/core";
import {
  buildGraph,
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
import { LlmReadinessHint } from "./LlmReadinessHint";

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
    : "无法连接本地服务，请确认 siku serve --with-ui 正在运行。";
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

export function GraphView({
  onAskEntity,
  onGoToSettings,
}: {
  onAskEntity: (name: string) => void;
  onGoToSettings: () => void;
}) {
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
  const [building, setBuilding] = useState(false);
  const [buildNote, setBuildNote] = useState<string | null>(null);
  // 各异步操作独立序号防竞态：慢响应不得覆盖同类新操作；
  // 跨操作不共用序号，避免被否决方的 loading 旗标永久卡死
  const loadSeqRef = useRef(0);
  const searchSeqRef = useRef(0);
  const expandSeqRef = useRef(0);
  const buildSeqRef = useRef(0);

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

  // 生成走服务端默认幂等缓存路径（等价 `siku graph` 默认行为）：
  // 未变语料零 LLM 调用；真实抽取可达分钟级，请求期不设前端超时
  const runBuild = useCallback(async () => {
    const seq = ++buildSeqRef.current;
    setBuilding(true);
    setActionError(null);
    setBuildNote(null);
    try {
      const report = await buildGraph();
      if (seq !== buildSeqRef.current) {
        return;
      }
      // 空语料同样落空产物（内核 save_graph 无条件执行），必须照常刷新：
      // 早退会让已建态残留旧画布，与磁盘产物不一致
      const warningSuffix =
        report.warnings.length > 0 ? `，${report.warnings.length} 条告警` : "";
      setBuildNote(
        report.empty_corpus
          ? "语料为空：图谱为空、无可展示内容；请先在「资料库」导入笔记。"
          : `图谱已构建：${report.nodes} 个实体、${report.edges} 条关系、` +
              `${report.communities} 个社区（LLM 调用 ${report.llm_calls} 次${warningSuffix}）。`,
      );
      await loadGraph();
    } catch (caught: unknown) {
      if (seq !== buildSeqRef.current) {
        return;
      }
      setActionError(connectionFallback(caught));
    } finally {
      if (seq === buildSeqRef.current) {
        setBuilding(false);
      }
    }
  }, [loadGraph]);

  const communityLegend = useMemo(() => {
    if (stats === null || stats.communities === 0) {
      return null;
    }
    return `${stats.communities} 个社区（颜色区分）`;
  }, [stats]);

  if (missing) {
    return (
      <Stack component="section" className="graph-view" gap="lg" aria-labelledby="graph-title">
        <GraphHeader />
        <Alert className="library-empty" color="gray" role="note" title="图谱尚未构建">
          <p>
            图谱由笔记投影抽取实体与关系生成，使用「设置」中配置的 LLM 通道；真实抽取
            可能需要几分钟，完成后画布自动加载。
          </p>
          <LlmReadinessHint onGoToSettings={onGoToSettings} />
          {buildNote !== null && (
            <p className="hint" role="status">
              {buildNote}
            </p>
          )}
          {actionError !== null && <Alert color="red" role="alert">{actionError}</Alert>}
          {/* 构建成功但数据面刷新失败（loadGraph 内部吞错）不得静默：
              否则「尚未构建」卡与「已构建」note 同屏矛盾 */}
          {loadError !== null && (
            <Alert color="red" role="alert">{loadError}</Alert>
          )}
          {loadError !== null && (
            <Button variant="default"
              type="button"
              className="button-secondary"
              disabled={building}
              onClick={() => void loadGraph()}
            >
              重试读取
            </Button>
          )}
          <Button type="button" disabled={building} onClick={() => void runBuild()}>
            {building ? "构建中…（可能需要几分钟）" : "构建图谱"}
          </Button>
        </Alert>
      </Stack>
    );
  }

  if (loadError !== null && model === null) {
    return (
      <Alert className="status-card" color="red" role="alert" title="图谱读取失败">
        <p>{loadError}</p>
        <Button variant="default"
          type="button"
          className="button-secondary"
          onClick={() => void loadGraph()}
        >
          重试读取
        </Button>
      </Alert>
    );
  }

  if (model === null) {
    return (
      <Group className="settings-loading" role="status" aria-live="polite" gap="sm">
        <Loader size="sm" />
        正在加载图谱…
      </Group>
    );
  }

  return (
    <Stack component="section" className="graph-view" gap="lg" aria-labelledby="graph-title">
      <GraphHeader
        action={
          <Button variant="default"
            type="button"
            className="button-secondary"
            disabled={building}
            onClick={() => void runBuild()}
          >
            {building ? "更新中…（可能需要几分钟）" : "更新图谱"}
          </Button>
        }
      />
      <p className="hint">
        {stats !== null
          ? `全图 ${stats.nodes} 个实体、${stats.edges} 条关系${communityLegend !== null ? `，${communityLegend}` : ""}。`
          : "画布展示度数最高的实体子集；搜索并展开邻域以探索更多。"}
      </p>

      {buildNote !== null && (
        <p className="hint" role="status">
          {buildNote}
        </p>
      )}

      {/* 已建态数据保留时 loadError 无渲染落点（全屏错误卡仅在 model===null）：
          生成成功但刷新失败必须显式告警，防统计与画布静默陈旧 */}
      {loadError !== null && (
        <Alert className="status-card" color="red" role="alert" title="图谱刷新失败">
          <p>{loadError}</p>
          <Button variant="default" type="button" className="button-secondary" onClick={() => void loadGraph()}>
            重试读取
          </Button>
        </Alert>
      )}

      <div className="graph-controls">
        <form
          className="graph-search"
          onSubmit={(event) => {
            event.preventDefault();
            void runSearch();
          }}
        >
          <TextInput
            id="graph-search-input"
            label="搜索实体"
            className="graph-search-field"
            value={searchQuery}
            placeholder="按实体名搜索…"
            onChange={(event) => setSearchQuery(event.target.value)}
          />
          <Button type="submit" loading={searching} disabled={searchQuery.trim() === ""}>
            {searching ? "搜索中…" : "搜索"}
          </Button>
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
              <Button
                key={node.entity_id}
                type="button"
                className={
                  selected?.entity_id === node.entity_id
                    ? "graph-chip graph-chip-active"
                    : "graph-chip"
                }
                variant="light"
                title={node.name}
                onClick={() => setSelected(node)}
              >
                {node.name}
              </Button>
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
          <Paper component="aside" withBorder shadow="xs" radius="md" className="graph-panel" aria-label="实体详情">
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
              <Button
                type="button"
                disabled={expanding || expanded.has(selected.entity_id)}
                onClick={() => void expandNeighborhood(selected)}
              >
                {expanded.has(selected.entity_id)
                  ? "邻域已展开"
                  : expanding
                    ? "展开中…"
                    : "展开邻域"}
              </Button>
              <Button variant="default" type="button" className="button-secondary" onClick={() => onAskEntity(selected.name)}>
                在问答中查询
              </Button>
            </div>
          </Paper>
        )}
      </div>
    </Stack>
  );
}

function GraphHeader({ action }: { action?: ReactNode }) {
  return (
    <Group component="header" className="graph-header" align="flex-start" justify="space-between" wrap="wrap">
      <div>
        <h2 id="graph-title">图谱</h2>
        <p className="hint">点击节点查看详情，服务端保证查询有界。</p>
      </div>
      {action !== undefined && <div className="graph-header-actions">{action}</div>}
    </Group>
  );
}

export default GraphView;
