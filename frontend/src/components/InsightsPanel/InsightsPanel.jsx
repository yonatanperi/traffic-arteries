import { IconClose, IconBulb } from "../icons";
import "../../styles/FloatingPanel.css";

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
    <div className="fp fp--end" role="dialog" aria-label="תובנות על הרשת">
      <header className="fp-head">
        <div className="fp-title-wrap">
          <IconBulb size={17} />
          <h3 className="fp-title">תובנות</h3>
        </div>
        <button
          type="button"
          className="fp-close"
          onClick={onClose}
          aria-label="סגור"
        >
          <IconClose size={16} />
        </button>
      </header>

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
          <ul className="fp-list">
            {hubs.map((h) => (
              <li key={h.id}>
                <button
                  type="button"
                  className="fp-list-btn"
                  onClick={() => onFocus(h.id)}
                >
                  <span className="fp-dot" aria-hidden="true" />
                  {h.id}
                  <span className="fp-list-meta">{h.degree}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {critical.length > 0 && (
        <section className="fp-section">
          <h4 className="fp-section-title">
            צמתים קריטיים
            <span className="fp-section-hint">נקודות תורפה ברשת</span>
          </h4>
          <ul className="fp-list">
            {critical.map((id) => (
              <li key={id}>
                <button
                  type="button"
                  className="fp-list-btn"
                  onClick={() => onFocus(id)}
                >
                  <span className="fp-dot fp-dot--warn" aria-hidden="true" />
                  {id}
                </button>
              </li>
            ))}
          </ul>
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
    </div>
  );
}
