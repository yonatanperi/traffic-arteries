import { useRef, useState } from "react";
import GraphView from "../../components/brain/GraphView";
import BrainToolbar from "../../components/brain/BrainToolbar";
import NodeDetailPanel from "../../components/brain/NodeDetailPanel";
import InsightsPanel from "../../components/brain/InsightsPanel";
import Loader from "../../components/ui/Loader";
import EmptyState from "../../components/ui/EmptyState";
import PageHeader from "../../components/ui/PageHeader";
import Page from "../../components/layout/Page";
import { IconAlert, IconNetwork } from "../../components/ui/icons";
import { useGraphData } from "./useGraphData.js";
import { usePathSearch } from "./usePathSearch.js";
import "./BrainPage.css";

export default function BrainPage() {
  const { data, loading, error, hasGraph, metrics, placeOptions, compromisedIds } =
    useGraphData();
  const path = usePathSearch();

  const graphRef = useRef(null);

  // View state
  const [mode, setMode] = useState("explore");
  const [pinnedId, setPinnedId] = useState(null);
  const [showInsights, setShowInsights] = useState(false);
  const [highlightDeadEnds, setHighlightDeadEnds] = useState(false);
  const [paused, setPaused] = useState(false);

  function focusNode(id) {
    setPinnedId(id);
    graphRef.current?.centerNode(id);
  }

  function changeMode(next) {
    setMode(next);
    if (next === "explore") path.clearPath();
    else setPinnedId(null);
  }

  return (
    <Page className="brain-page">
      <PageHeader
        title="הצצה למוח"
        subtitle="רשת הצמתים החיה של המערכת. חפשו מקום, סמנו צומת לפרטים, או שרטטו ציר בין שתי נקודות — והציצו במבנה הפנימי של הרשת."
      />

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
          onSubmitPath={path.submitPath}
          onClearPath={path.clearPath}
          onSelectPathIndex={path.setActivePathIndex}
          pathLoading={path.pathLoading}
          pathError={path.pathError}
          pathResult={path.pathResult}
          activePathIndex={path.activePathIndex}
          vias={path.vias}
          onAddVia={path.addVia}
          onSetVia={path.setVia}
          onRemoveVia={path.removeVia}
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
              pathNodes={path.pathNodes}
              pathEdges={path.pathEdges}
              waypointIds={path.waypointIds}
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
    </Page>
  );
}
