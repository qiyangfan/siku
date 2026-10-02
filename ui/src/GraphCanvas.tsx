import { useCallback, useEffect, useRef } from "react";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import Sigma from "sigma";
import { useComputedColorScheme } from "@mantine/core";
import type { GraphEdge, GraphNode } from "./api";
import { GRAPH_COMMUNITY_COLORS, GRAPH_UNASSIGNED_COLOR, graphCanvasThemeColors } from "./theme";

/** 画布数据边界：永远只渲染服务端有界查询的返回集合。 */
export type GraphCanvasProps = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedId: string | null;
  onSelect: (node: GraphNode) => void;
};

function communityColor(communityId: number | null): string {
  if (communityId === null) {
    return GRAPH_UNASSIGNED_COLOR;
  }
  return (
    GRAPH_COMMUNITY_COLORS[Math.abs(communityId) % GRAPH_COMMUNITY_COLORS.length] ??
    GRAPH_UNASSIGNED_COLOR
  );
}

/** 度数 → 节点视觉尺寸：有界放缩，避免超级枢纽吞噬画布。 */
function nodeSize(degree: number): number {
  return 4 + Math.min(Math.sqrt(Math.max(degree, 0)) * 2.2, 16);
}

export function GraphCanvas({ nodes, edges, selectedId, onSelect }: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);
  const rendererRef = useRef<Sigma | null>(null);
  const selectedRef = useRef<string | null>(null);
  const nodesByIdRef = useRef<Map<string, GraphNode>>(new Map());
  const onSelectRef = useRef(onSelect);
  // 画布绘制的边线/标签色读不到 CSS 变量（theme.ts 登记的第二处 canvas 例外），
  // 按解析后的主题取值；经 ref 中转避免把主题变更接进数据重建（重建会重掷布局坐标）
  const colorScheme = useComputedColorScheme("light", { getInitialValueInEffect: false });
  const colorSchemeRef = useRef(colorScheme);
  colorSchemeRef.current = colorScheme;

  onSelectRef.current = onSelect;

  /** 灌入当前有界数据集：整体重建图内容（≤ 数百节点，代价可忽略）。 */
  const rebuildData = useCallback(() => {
    const graph = graphRef.current;
    const renderer = rendererRef.current;
    if (graph === null || renderer === null) {
      return;
    }
    const canvasColors = graphCanvasThemeColors(colorSchemeRef.current);
    graph.clear();
    nodesByIdRef.current = new Map();
    for (const node of nodes) {
      if (!graph.hasNode(node.entity_id)) {
        graph.addNode(node.entity_id, {
          label: node.name,
          x: Math.random(),
          y: Math.random(),
          baseSize: nodeSize(node.degree),
          size: nodeSize(node.degree),
          color: communityColor(node.community_id),
        });
        nodesByIdRef.current.set(node.entity_id, node);
      }
    }
    for (const edge of edges) {
      if (graph.hasNode(edge.source) && graph.hasNode(edge.target)) {
        graph.addEdge(edge.source, edge.target, {
          size: 1,
          color: canvasColors.edge,
          type: "line",
        });
      }
    }
    forceAtlas2.assign(graph, {
      iterations: 120,
      settings: forceAtlas2.inferSettings(graph),
    });
    applySelection(graph, renderer, selectedRef.current);
    renderer.refresh();
  }, [nodes, edges]);

  /** 选中高亮：选中节点放大并平移相机聚焦，其余恢复基准尺寸。 */
  const applySelection = (graph: Graph, renderer: Sigma, nodeId: string | null) => {
    for (const id of graph.nodes()) {
      const baseSize = graph.getNodeAttribute(id, "baseSize") as number | undefined;
      const base = baseSize ?? 6;
      graph.setNodeAttribute(id, "size", id === nodeId ? base * 1.8 : base);
    }
    renderer.refresh();
  };

  useEffect(() => {
    const container = containerRef.current;
    if (container === null) {
      return;
    }
    const graph = new Graph({ multi: true });
    // Sigma v3：第三参即 Settings（无 v2 的 {settings} 包装）
    const renderer = new Sigma(graph, container, {
      allowInvalidContainer: true,
      renderEdgeLabels: false,
      defaultEdgeType: "line",
      labelSize: 12,
      labelRenderedSizeThreshold: 9,
    });
    renderer.on("clickNode", ({ node }) => {
      const payload = nodesByIdRef.current.get(node);
      if (payload !== undefined) {
        onSelectRef.current(payload);
      }
    });
    graphRef.current = graph;
    rendererRef.current = renderer;
    // 首个数据集由数据 effect（声明于本 effect 之后，挂载时必然随后执行）灌入
    return () => {
      renderer.kill();
      graphRef.current = null;
      rendererRef.current = null;
      nodesByIdRef.current = new Map();
    };
  }, []);

  useEffect(() => {
    rebuildData();
  }, [rebuildData]);

  // 主题切换就地重着色：只改边线色与标签色并刷新，不重建数据（保持布局坐标）
  useEffect(() => {
    const graph = graphRef.current;
    const renderer = rendererRef.current;
    if (graph === null || renderer === null) {
      return;
    }
    const canvasColors = graphCanvasThemeColors(colorScheme);
    graph.forEachEdge((edge) => graph.setEdgeAttribute(edge, "color", canvasColors.edge));
    renderer.setSettings({ labelColor: { color: canvasColors.label } });
    renderer.refresh();
  }, [colorScheme]);

  useEffect(() => {
    const graph = graphRef.current;
    const renderer = rendererRef.current;
    if (graph === null || renderer === null) {
      return;
    }
    if (selectedId !== null && graph.hasNode(selectedId)) {
      const position = renderer.getNodeDisplayData(selectedId);
      if (position !== undefined) {
        renderer.getCamera().animate(position, { duration: 240 });
      }
    }
    selectedRef.current = selectedId;
    applySelection(graph, renderer, selectedId);
  }, [selectedId]);

  return <div ref={containerRef} className="graph-canvas" role="img" aria-label="图谱画布" />;
}

export default GraphCanvas;
