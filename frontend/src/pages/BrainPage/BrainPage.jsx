import { useEffect, useMemo, useRef, useState } from "react";
import GraphView from "../../components/GraphView";
import BrainToolbar from "../../components/BrainToolbar";
import NodeDetailPanel from "../../components/NodeDetailPanel";
import InsightsPanel from "../../components/InsightsPanel";
import Loader from "../../components/Loader";
import EmptyState from "../../components/EmptyState";
import { IconAlert, IconNetwork } from "../../components/icons";
import { getGraph, findPaths } from "../../api/client.js";
import { computeMetrics, edgeKey } from "../../utils/graphMetrics.js";
import "./BrainPage.css";

export default function BrainPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const graphRef = useRef(null);

  // View state
  const [mode, setMode] = useState("explore");
  const [pinnedId, setPinnedId] = useState(null);
  const [showInsights, setShowInsights] = useState(false);
  const [highlightDeadEnds, setHighlightDeadEnds] = useState(false);
  const [paused, setPaused] = useState(false);

  // Path mode state
  const [pathResult, setPathResult] = useState(null); // { paths } | null
  const [pathLoading, setPathLoading] = useState(false);
  const [pathError, setPathError] = useState("");
  const [activePathIndex, setActivePathIndex] = useState(0);

  useEffect(() => {
    getGraph()
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const hasGraph = !loading && !error && data && data.nodes.length > 0;

  const metrics = useMemo(() => (data ? computeMetrics(data) : null), [data]);

  const placeOptions = useMemo(
    () => (data ? data.nodes.map((n) => n.id) : []),
    [data],
  );

  // Destinations temporarily marked unavailable — still shown, painted red.
  const compromisedIds = useMemo(
    () => new Set(data ? data.nodes.filter((n) => n.compromised).map((n) => n.id) : []),
    [data],
  );

  // Nodes / edges of the currently highlighted path (path mode only).
  const { pathNodes, pathEdges } = useMemo(() => {
    const path = pathResult?.paths?.[activePathIndex];
    if (!path) return { pathNodes: null, pathEdges: null };
    const nodes = new Set(path);
    const edges = new Set();
    for (let i = 0; i < path.length - 1; i += 1) {
      edges.add(edgeKey(path[i], path[i + 1]));
    }
    return { pathNodes: nodes, pathEdges: edges };
  }, [pathResult, activePathIndex]);

  function focusNode(id) {
    setPinnedId(id);
    graphRef.current?.centerNode(id);
  }

  async function submitPath(start, end) {
    setPathError("");
    setPathLoading(true);
    setPathResult(null);
    setPinnedId(null);
    try {
      const res = await findPaths(start, end);
      setPathResult(res);
      setActivePathIndex(0);
    } catch (e) {
      setPathError(e.message);
    } finally {
      setPathLoading(false);
    }
  }

  function clearPath() {
    setPathResult(null);
    setPathError("");
    setActivePathIndex(0);
  }

  function changeMode(next) {
    setMode(next);
    if (next === "explore") clearPath();
    else setPinnedId(null);
  }

  return (
    <div className="page brain-page">
      <div className="page-header">
        <h1 className="page-title">הצצה למוח</h1>
        <p className="page-subtitle">
          רשת הצמתים החיה של המערכת. חפשו מקום, סמנו צומת לפרטים, או שרטטו ציר
          בין שתי נקודות — והציצו במבנה הפנימי של הרשת.
        </p>
      </div>

      {hasGraph && (
        <BrainToolbar
          mode={mode}
          onModeChange={changeMode}
          placeOptions={placeOptions}
          onFocusNode={focusNode}
          onZoomFit={() => graphRef.current?.zoomToFit()}
          onReset={() => graphRef.current?.reheat()}
          paused={paused}
          onTogglePause={() => setPaused((p) => !p)}
          highlightDeadEnds={highlightDeadEnds}
          onToggleDeadEnds={() => setHighlightDeadEnds((v) => !v)}
          showInsights={showInsights}
          onToggleInsights={() => setShowInsights((v) => !v)}
          onExport={() => graphRef.current?.exportPng()}
          onSubmitPath={submitPath}
          onClearPath={clearPath}
          onSelectPathIndex={setActivePathIndex}
          pathLoading={pathLoading}
          pathError={pathError}
          pathResult={pathResult}
          activePathIndex={activePathIndex}
        />
      )}

      <div className="brain-canvas-wrap">
        {loading && <Loader label="בונה את הרשת…" />}
        {error && (
          <EmptyState
            icon={<IconAlert size={60} />}
            tone="danger"
            title="שגיאה בטעינת הגרף"
            message={error}
          />
        )}
        {!loading && !error && data && data.nodes.length === 0 && (
          <EmptyState
            icon={<IconNetwork size={60} />}
            title="הרשת ריקה"
            message="עדיין אין צירים. הוסיפו צירים בעמוד עריכת הצירים כדי לראות את הרשת מתעוררת לחיים."
          />
        )}
        {hasGraph && (
          <>
            <GraphView
              ref={graphRef}
              data={data}
              pinnedId={pinnedId}
              onPinNode={setPinnedId}
              componentOf={metrics.componentOf}
              pathNodes={pathNodes}
              pathEdges={pathEdges}
              deadEndIds={metrics.deadEndIds}
              highlightDeadEnds={highlightDeadEnds}
              compromisedIds={compromisedIds}
              paused={paused}
            />

            {pinnedId && mode === "explore" && (
              <NodeDetailPanel
                id={pinnedId}
                adjacency={metrics.adjacency}
                onClose={() => setPinnedId(null)}
                onFocus={focusNode}
              />
            )}

            {showInsights && (
              <InsightsPanel
                metrics={metrics}
                nodeCount={data.nodes.length}
                linkCount={data.links.length}
                onClose={() => setShowInsights(false)}
                onFocus={focusNode}
                onShowDeadEnds={() => setHighlightDeadEnds(true)}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
