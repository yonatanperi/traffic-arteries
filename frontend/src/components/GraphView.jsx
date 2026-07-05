import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import "./GraphView.css";

const ACCENT = "#d5ff40";
const ACCENT_2 = "#eaff8f";
const DIM = "#40412f";
const TEXT = "#ffffff";

/**
 * Read-only interactive force-directed graph. Nodes can be dragged, the view
 * zoomed/panned, and hovering a node highlights its direct connections.
 */
export default function GraphView({ data }) {
  const wrapRef = useRef(null);
  const fgRef = useRef(null);
  const [size, setSize] = useState({ width: 800, height: 600 });
  const [hoverNode, setHoverNode] = useState(null);

  // Adjacency lookup for highlight logic.
  const neighbours = useMemo(() => {
    const map = new Map();
    data.nodes.forEach((n) => map.set(n.id, new Set()));
    data.links.forEach((l) => {
      const s = typeof l.source === "object" ? l.source.id : l.source;
      const t = typeof l.target === "object" ? l.target.id : l.target;
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
      const s = typeof l.source === "object" ? l.source.id : l.source;
      const t = typeof l.target === "object" ? l.target.id : l.target;
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

  const isActive = useCallback(
    (id) =>
      !hoverNode ||
      id === hoverNode ||
      neighbours.get(hoverNode)?.has(id),
    [hoverNode, neighbours]
  );

  const drawNode = useCallback(
    (node, ctx, globalScale) => {
      const active = isActive(node.id);
      const deg = degree.get(node.id) || 1;
      const radius = 4 + Math.min(deg, 6) * 0.9;

      // Node circle
      ctx.beginPath();
      ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
      if (node.id === hoverNode) {
        ctx.fillStyle = ACCENT_2;
      } else if (active) {
        ctx.fillStyle = ACCENT;
      } else {
        ctx.fillStyle = DIM;
      }
      ctx.globalAlpha = active ? 1 : 0.3;
      ctx.fill();

      if (node.id === hoverNode) {
        ctx.lineWidth = 2 / globalScale;
        ctx.strokeStyle = "rgba(255,255,255,0.85)";
        ctx.stroke();
      }

      // Label
      const fontSize = Math.max(11 / globalScale, 3.2);
      ctx.font = `600 ${fontSize}px Heebo, Assistant, system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillStyle = active ? TEXT : "rgba(154,167,194,0.5)";
      ctx.globalAlpha = active ? 1 : 0.4;
      ctx.fillText(node.id, node.x, node.y + radius + 1.5);
      ctx.globalAlpha = 1;
    },
    [degree, hoverNode, isActive]
  );

  const linkColor = useCallback(
    (link) => {
      if (!hoverNode) return "rgba(213,255,64,0.16)";
      const s = typeof link.source === "object" ? link.source.id : link.source;
      const t = typeof link.target === "object" ? link.target.id : link.target;
      const touches = s === hoverNode || t === hoverNode;
      return touches ? "rgba(213,255,64,0.9)" : "rgba(64,65,47,0.2)";
    },
    [hoverNode]
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
        linkWidth={(l) => {
          if (!hoverNode) return 1;
          const s = typeof l.source === "object" ? l.source.id : l.source;
          const t = typeof l.target === "object" ? l.target.id : l.target;
          return s === hoverNode || t === hoverNode ? 2 : 0.6;
        }}
        onNodeHover={(n) => setHoverNode(n ? n.id : null)}
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
}
