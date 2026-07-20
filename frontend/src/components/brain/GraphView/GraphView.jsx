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
import { linkEnds, edgeKey } from "../../../utils/graphMetrics.js";
import "./GraphView.css";

const ACCENT = "#d5ff40";
const ACCENT_2 = "#eaff8f";
const DIM = "#40412f";
const TEXT = "#ffffff";
const WARNING = "#e2c541";
const COMPROMISED = "#f85149"; // --danger: destinations temporarily unavailable.
const WAYPOINT = "#58a6ff"; // --info: stops the active path is required to pass through.

// Minimum screen-space gap enforced between neighbouring labels.
const LABEL_SCREEN_PADDING = 4;

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return `${(n >> 16) & 255},${(n >> 8) & 255},${n & 255}`;
}
const ACCENT_RGB = hexToRgb(ACCENT);

/**
 * Interactive force-directed graph of the place network.
 *
 * Beyond drag / zoom / pan it supports: hover- and click-to-pin highlighting of
 * a node and its direct connections, monochrome dimming of other connected
 * components, path highlighting (with required waypoint stops painted
 * separately), and a dead-end ring overlay. Imperative controls (fit / zoom
 * / reheat / center) are exposed through the ref.
 */
const GraphView = forwardRef(function GraphView(
  {
    data,
    pinnedId = null,
    onPinNode,
    componentOf = null,
    pathNodes = null,
    pathEdges = null,
    waypointIds = null,
    deadEndIds = null,
    highlightDeadEnds = false,
    compromisedIds = null,
  },
  ref,
) {
  const wrapRef = useRef(null);
  const fgRef = useRef(null);
  const didInitialFit = useRef(false);
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

  // A fresh dataset gets one automatic fit, fired once its layout actually
  // settles (onEngineStop) rather than after a guessed delay — so the graph
  // renders at its full extent from the start instead of needing a manual
  // re-fit once the simulation keeps spreading past an early snapshot.
  useEffect(() => {
    didInitialFit.current = false;
  }, [data]);

  // The library's default charge (repulsion) is tuned for sparse graphs and
  // settles this network into a tight, overlapping cluster on its own — the
  // old manual "reset" button only looked like it fixed that by re-running
  // the simulation with fresh velocity each click, letting repulsion win a
  // little more ground each time. Push the repulsion up front instead, so
  // the very first settle already lands at that fully-spread layout.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force("charge")?.strength(-300).distanceMax(1000);
    fg.d3Force("link")?.distance(70);
    fg.d3ReheatSimulation();
  }, [data]);

  useImperativeHandle(ref, () => ({
    zoomToFit: () => fgRef.current?.zoomToFit(600, 60),
    reheat: () => fgRef.current?.d3ReheatSimulation(),
    zoomIn: () => {
      const fg = fgRef.current;
      if (!fg) return;
      fg.zoom(fg.zoom() * 1.4, 300);
    },
    zoomOut: () => {
      const fg = fgRef.current;
      if (!fg) return;
      fg.zoom(fg.zoom() / 1.4, 300);
    },
    centerNode: (id) => {
      const node = data.nodes.find((n) => n.id === id);
      if (!node) return;
      fgRef.current?.centerAt(node.x, node.y, 700);
      fgRef.current?.zoom(3.2, 700);
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
    [pathActive, pathNodes, selected, neighbours, componentOf],
  );

  /**
   * A node's special-status color, if any (compromised wins over waypoint,
   * matching drawNode's paint order) — independent of interaction tier. Every
   * link touching such a node is tinted to match, at the same tone/weight
   * already used for "touches the selected node" / "on the active path".
   */
  const overrideColorOf = useCallback(
    (id) => {
      if (compromisedIds?.has(id)) return COMPROMISED;
      if (waypointIds?.has(id)) return WAYPOINT;
      return null;
    },
    [compromisedIds, waypointIds],
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

      // A node's special-status color always overrides the tier fill, but
      // not its alpha, so it still dims correctly when off-path/off-component.
      const override = overrideColorOf(node.id);
      if (override) fill = override;

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
    },
    [
      tierOf,
      degree,
      highlightDeadEnds,
      deadEndIds,
      pathActive,
      overrideColorOf,
    ],
  );

  /**
   * Draws node labels as a separate pass so placement can be decided
   * globally instead of node-by-node: nodes the user is actively engaging
   * with (selected / neighbours / path) always get a label and claim their
   * space first, then the rest compete for remaining room in order of
   * importance (busiest hubs win). A label is skipped whenever it would
   * overlap one already placed, so a zoomed-out view naturally keeps only
   * the labels that fit — exactly the declutter-as-you-zoom-in effect maps
   * use — without any dataset-size-dependent tuning.
   */
  const paintLabels = useCallback(
    (ctx, globalScale) => {
      const fontSize = Math.max(11 / globalScale, 3.2);
      ctx.font = `600 ${fontSize}px Heebo, Assistant, system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      const pad = LABEL_SCREEN_PADDING / globalScale;

      const always = [];
      const candidates = [];
      data.nodes.forEach((node) => {
        const tier = tierOf(node.id);
        if (tier === "selected" || tier === "neighbour" || tier === "path") {
          always.push(node);
        } else {
          candidates.push(node);
        }
      });
      candidates.sort(
        (a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0),
      );

      const placed = [];
      const tryPlace = (node, force) => {
        const deg = degree.get(node.id) || 1;
        const radius = 4 + Math.min(deg, 6) * 0.9;
        const width = ctx.measureText(node.id).width;
        const top = node.y + radius + 1.5;
        const rect = {
          left: node.x - width / 2 - pad,
          right: node.x + width / 2 + pad,
          top: top - pad,
          bottom: top + fontSize + pad,
        };
        if (!force) {
          const overlaps = placed.some(
            (r) =>
              rect.left < r.right &&
              rect.right > r.left &&
              rect.top < r.bottom &&
              rect.bottom > r.top,
          );
          if (overlaps) return;
        }
        placed.push(rect);

        const tier = tierOf(node.id);
        const bright =
          tier === "selected" ||
          tier === "neighbour" ||
          tier === "normal" ||
          tier === "path";
        ctx.fillStyle = bright ? TEXT : "rgba(154,167,194,0.5)";
        ctx.globalAlpha = bright ? 1 : 0.4;
        ctx.fillText(node.id, node.x, top);
        ctx.globalAlpha = 1;
      };

      always.forEach((node) => tryPlace(node, true));
      candidates.forEach((node) => tryPlace(node, false));
    },
    [data, tierOf, degree],
  );

  const linkColor = useCallback(
    (link) => {
      const [s, t] = linkEnds(link);
      const overrideHex = overrideColorOf(s) || overrideColorOf(t);
      if (pathActive) {
        const on = pathEdges?.has(edgeKey(s, t));
        if (!on) return "rgba(64,65,47,0.15)";
        return `rgba(${overrideHex ? hexToRgb(overrideHex) : ACCENT_RGB},0.95)`;
      }
      if (overrideHex) return `rgba(${hexToRgb(overrideHex)},0.9)`;
      if (!selected) return "rgba(213,255,64,0.16)";
      const touches = s === selected || t === selected;
      return touches ? "rgba(213,255,64,0.9)" : "rgba(64,65,47,0.2)";
    },
    [pathActive, pathEdges, selected, overrideColorOf],
  );

  const linkWidth = useCallback(
    (link) => {
      const [s, t] = linkEnds(link);
      if (pathActive) return pathEdges?.has(edgeKey(s, t)) ? 3 : 0.6;
      if (overrideColorOf(s) || overrideColorOf(t)) return 2;
      if (!selected) return 1;
      return s === selected || t === selected ? 2 : 0.6;
    },
    [pathActive, pathEdges, selected, overrideColorOf],
  );

  return (
    <div className="graph-view" ref={wrapRef}>
      <ForceGraph2D
        ref={fgRef}
        width={size.width}
        height={size.height}
        graphData={data}
        backgroundColor="rgba(0,0,0,0)"
        d3VelocityDecay={0.28}
        nodeRelSize={5}
        nodeLabel={() => ""}
        linkColor={linkColor}
        linkWidth={linkWidth}
        onNodeHover={(n) => setHoverNode(n ? n.id : null)}
        onNodeClick={(n) => onPinNode?.(n ? n.id : null)}
        onBackgroundClick={() => onPinNode?.(null)}
        onEngineStop={() => {
          if (didInitialFit.current) return;
          didInitialFit.current = true;
          fgRef.current?.zoomToFit(600, 60);
        }}
        nodeCanvasObject={drawNode}
        onRenderFramePost={paintLabels}
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
