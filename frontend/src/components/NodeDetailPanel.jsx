import { IconClose, IconHub } from "./icons.jsx";
import "./FloatingPanel.css";

/**
 * Floating card describing the pinned node: its degree and the list of places
 * it connects to directly. Clicking a neighbour re-pins and centers on it.
 */
export default function NodeDetailPanel({ id, adjacency, onClose, onFocus }) {
  if (!id) return null;
  const neighbours = [...(adjacency.get(id) ?? [])].sort((a, b) =>
    a.localeCompare(b)
  );

  return (
    <div className="fp fp--start" role="dialog" aria-label={`פרטי ${id}`}>
      <header className="fp-head">
        <div className="fp-title-wrap">
          <IconHub size={17} />
          <h3 className="fp-title">{id}</h3>
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

      <div className="fp-badge-row">
        <span className="fp-badge">
          <strong>{neighbours.length}</strong> חיבורים ישירים
        </span>
      </div>

      {neighbours.length > 0 ? (
        <ul className="fp-list">
          {neighbours.map((n) => (
            <li key={n}>
              <button
                type="button"
                className="fp-list-btn"
                onClick={() => onFocus(n)}
              >
                <span className="fp-dot" aria-hidden="true" />
                {n}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="fp-empty">מקום מבודד — ללא חיבורים.</p>
      )}
    </div>
  );
}
