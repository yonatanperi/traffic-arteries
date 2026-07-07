import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import ForceGraph2D from "react-force-graph-2d";
import { linkEnds, edgeKey } from "../utils/graphMetrics.js";
import "./GraphView.css";

const ACCENT = "#d5ff40";
const ACCENT_2 = "#eaff8f";
const DIM = "#40412f";
const TEXT = "#ffffff";
const WARNING = "#e2c541";
const EXPORT_BG = "#141510"; // --bg-elevated, so exported PNGs aren't transparent.

/**
 * Interactive force-directed graph of the place network.
 *
 * Beyond drag / zoom / pan it supports: hover- and click-to-pin highlighting of
 * a node and its direct connections, monochrome dimming of other connected
 * components, path highlighting, and a dead-end ring overlay. Imperative
 * controls (fit / reheat / center / export) are exposed through the ref.
 */
const GraphView = forwardRef(function GraphView(
  {
    data,
    pinnedId = null,
    onPinNode,
    componentOf = null,
    pathNodes = null,
    pathEdges = null,
    deadEndIds = null,
    highlightDeadEnds = false,
    paused = false,
  },
  ref
) {
  const wrapRef = useRef(null);
  const fgRef = useRef(null);
  const [size, setSize] = useState({ width: 800, height: 600 });
  const [hoverNode, setHoverNode] = useState(null);

  const selected = hoverNode ?? pinnedId;
  const pathActive = !!(pathNodes && pathNodes.size > 0);

  // Adjacency lookup for highlight logic.
  const neighbours = useMemo(() => {
    const map = new Map();
    data.nodes.forEach((n) => map.set(n.id, new Set()));
    data.links.forEach((l) => {
      const [s, t] = linkEnds(l);
      map.get(s)?.add(t);
      map.get(t)?.add(s);
    });
    return map;
  }, [data]);

  // Track degree so busier hubs render larger.
  const degree = useMemo(() => {
    const d = new Map();
    data.nodes.forEach((n) => d.set(n.id, 0));
    data.links.forEach((l) => {
      const [s, t] = linkEnds(l);
      d.set(s, (d.get(s) || 0) + 1);
      d.set(t, (d.get(t) || 0) + 1);
    });
    return d;
  }, [data]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      setSize({ width, height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Gentle initial zoom-to-fit once the layout settles.
  useEffect(() => {
    const t = setTimeout(() => fgRef.current?.zoomToFit(600, 60), 600);
    return () => clearTimeout(t);
  }, [data]);

  // Freeze / resume the simulation on demand.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    if (paused) fg.pauseAnimation();
    else fg.resumeAnimation();
  }, [paused]);

  useImperativeHandle(ref, () => ({
    zoomToFit: () => fgRef.current?.zoomToFit(600, 60),
    reheat: () => fgRef.current?.d3ReheatSimulation(),
    centerNode: (id) => {
      const node = data.nodes.find((n) => n.id === id);
      if (!node) return;
      fgRef.current?.centerAt(node.x, node.y, 700);
      fgRef.current?.zoom(3.2, 700);
    },
    exportPng: () => {
      const canvas = wrapRef.current?.querySelector("canvas");
      if (!canvas) return;
      // Composite onto the elevated background so the PNG isn't transparent.
      const out = document.createElement("canvas");
      out.width = canvas.width;
      out.height = canvas.height;
      const ctx = out.getContext("2d");
      ctx.fillStyle = EXPORT_BG;
      ctx.fillRect(0, 0, out.width, out.height);
      ctx.drawImage(canvas, 0, 0);
      const a = document.createElement("a");
      a.href = out.toDataURL("image/png");
      a.download = "traffic-brain.png";
      a.click();
    },
  }));

  /**
   * Visual tier for a node id, most-highlighted first. Path mode overrides the
   * hover/pin logic entirely; neighbour highlighting always wins over the
   * softer same-component / other-component dimming.
   */
  const tierOf = useCallback(
    (id) => {
      if (pathActive) return pathNodes.has(id) ? "path" : "dim";
      if (!selected) return "normal";
      if (id === selected) return "selected";
      if (neighbours.get(selected)?.has(id)) return "neighbour";
      if (componentOf && componentOf.get(id) === componentOf.get(selected)) {
        return "component";
      }
      return "dim";
    },
    [pathActive, pathNodes, selected, neighbours, componentOf]
  );

  const drawNode = useCallback(
    (node, ctx, globalScale) => {
      const tier = tierOf(node.id);
      const deg = degree.get(node.id) || 1;
      const radius = 4 + Math.min(deg, 6) * 0.9;

      let fill = ACCENT;
      let alpha = 1;
      if (tier === "selected" || tier === "path") fill = ACCENT_2;
      else if (tier === "neighbour" || tier === "normal") fill = ACCENT;
      else if (tier === "component") {
        fill = ACCENT;
        alpha = 0.55;
      } else if (tier === "dim") {
        fill = DIM;
        alpha = 0.3;
      }

      ctx.beginPath();
      ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
      ctx.fillStyle = fill;
      ctx.globalAlpha = alpha;
      ctx.fill();

      // Dead-end ring overlay.
      if (highlightDeadEnds && deadEndIds?.has(node.id) && !pathActive) {
        ctx.lineWidth = 2 / globalScale;
        ctx.strokeStyle = WARNING;
        ctx.globalAlpha = Math.max(alpha, 0.7);
        ctx.beginPath();
        ctx.arc(node.x, node.y, radius + 2.5 / globalScale + 1, 0, 2 * Math.PI);
        ctx.stroke();
      }

      // Selected node gets a bright outline.
      if (tier === "selected") {
        ctx.lineWidth = 2 / globalScale;
        ctx.strokeStyle = "rgba(255,255,255,0.85)";
        ctx.globalAlpha = 1;
        ctx.beginPath();
        ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
        ctx.stroke();
      }

      // Label
      const bright = tier === "selected" || tier === "neighbour" ||
        tier === "normal" || tier === "path";
      const fontSize = Math.max(11 / globalScale, 3.2);
      ctx.font = `600 ${fontSize}px Heebo, Assistant, system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = bright ? TEXT : "rgba(154,167,194,0.5)";
      ctx.globalAlpha = bright ? 1 : 0.4;
      ctx.fillText(node.id, node.x, node.y + radius + 1.5);
      ctx.globalAlpha = 1;
    },
    [tierOf, degree, highlightDeadEnds, deadEndIds, pathActive]
  );

  const linkColor = useCallback(
    (link) => {
      const [s, t] = linkEnds(link);
      if (pathActive) {
        const on = pathEdges?.has(edgeKey(s, t));
        return on ? "rgba(213,255,64,0.95)" : "rgba(64,65,47,0.15)";
      }
      if (!selected) return "rgba(213,255,64,0.16)";
      const touches = s === selected || t === selected;
      return touches ? "rgba(213,255,64,0.9)" : "rgba(64,65,47,0.2)";
    },
    [pathActive, pathEdges, selected]
  );

  const linkWidth = useCallback(
    (link) => {
      const [s, t] = linkEnds(link);
      if (pathActive) return pathEdges?.has(edgeKey(s, t)) ? 3 : 0.6;
      if (!selected) return 1;
      return s === selected || t === selected ? 2 : 0.6;
    },
    [pathActive, pathEdges, selected]
  );

  return (
    <div className="graph-view" ref={wrapRef}>
      <ForceGraph2D
        ref={fgRef}
        width={size.width}
        height={size.height}
        graphData={data}
        backgroundColor="rgba(0,0,0,0)"
        cooldownTicks={120}
        d3VelocityDecay={0.28}
        nodeRelSize={5}
        nodeLabel={() => ""}
        linkColor={linkColor}
        linkWidth={linkWidth}
        onNodeHover={(n) => setHoverNode(n ? n.id : null)}
        onNodeClick={(n) => onPinNode?.(n ? n.id : null)}
        onBackgroundClick={() => onPinNode?.(null)}
        nodeCanvasObject={drawNode}
        nodePointerAreaPaint={(node, color, ctx) => {
          const deg = degree.get(node.id) || 1;
          const radius = 4 + Math.min(deg, 6) * 0.9;
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(node.x, node.y, radius + 3, 0, 2 * Math.PI);
          ctx.fill();
        }}
      />
    </div>
  );
});

export default GraphView;
