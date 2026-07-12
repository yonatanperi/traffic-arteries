import { IconBulb } from "../icons";
import FloatingPanel, { FloatingPanelList, FloatingPanelListItem } from "../FloatingPanel";

/**
 * Floating card of structural insights into the network: size, busiest hubs,
 * number of separate clusters, critical (articulation) nodes, and dead-ends.
 * Hubs and critical nodes are clickable to focus them on the graph.
 */
export default function InsightsPanel({
  metrics,
  nodeCount,
  linkCount,
  onClose,
  onFocus,
  onShowDeadEnds,
}) {
  const { hubs, components, articulation, deadEnds } = metrics;
  const clusters = components.length;
  const critical = [...articulation].sort((a, b) => a.localeCompare(b));
  const deadEndCount = deadEnds.isolated.length + deadEnds.leaves.length;

  return (
    <FloatingPanel
      side="end"
      icon={<IconBulb size={17} />}
      title="תובנות"
      onClose={onClose}
      ariaLabel="תובנות על הרשת"
    >
      <div className="fp-stat-grid">
        <div className="fp-stat">
          <strong>{nodeCount}</strong>
          <span>מקומות</span>
        </div>
        <div className="fp-stat">
          <strong>{linkCount}</strong>
          <span>חיבורים</span>
        </div>
        <div className="fp-stat">
          <strong>{clusters}</strong>
          <span>{clusters === 1 ? "רשת אחת" : "רשתות נפרדות"}</span>
        </div>
      </div>

      {hubs.length > 0 && (
        <section className="fp-section">
          <h4 className="fp-section-title">צמתים מרכזיים</h4>
          <FloatingPanelList>
            {hubs.map((h) => (
              <FloatingPanelListItem key={h.id} onClick={() => onFocus(h.id)} meta={h.degree}>
                {h.id}
              </FloatingPanelListItem>
            ))}
          </FloatingPanelList>
        </section>
      )}

      {critical.length > 0 && (
        <section className="fp-section">
          <h4 className="fp-section-title">
            צמתים קריטיים
            <span className="fp-section-hint">נקודות תורפה ברשת</span>
          </h4>
          <FloatingPanelList>
            {critical.map((id) => (
              <FloatingPanelListItem key={id} onClick={() => onFocus(id)} warn>
                {id}
              </FloatingPanelListItem>
            ))}
          </FloatingPanelList>
        </section>
      )}

      <section className="fp-section">
        <button
          type="button"
          className="fp-deadend-btn"
          onClick={onShowDeadEnds}
          disabled={deadEndCount === 0}
        >
          <span className="fp-dot fp-dot--warn" aria-hidden="true" />
          {deadEndCount === 0
            ? "אין קצוות מבודדים"
            : `${deadEndCount} קצוות מבודדים — הדגש`}
        </button>
      </section>
    </FloatingPanel>
  );
}
