import { IconHub } from "../../ui/icons";
import Pill from "../../ui/Pill";
import FloatingPanel, { FloatingPanelList, FloatingPanelListItem } from "../../ui/FloatingPanel";

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
    <FloatingPanel
      side="start"
      icon={<IconHub size={17} />}
      title={id}
      onClose={onClose}
      ariaLabel={`פרטי ${id}`}
    >
      <div className="fp-badge-row">
        <Pill size="md" tone="accent" className="fp-badge">
          <strong>{neighbours.length}</strong> חיבורים ישירים
        </Pill>
      </div>

      {neighbours.length > 0 ? (
        <FloatingPanelList>
          {neighbours.map((n) => (
            <FloatingPanelListItem key={n} onClick={() => onFocus(n)}>
              {n}
            </FloatingPanelListItem>
          ))}
        </FloatingPanelList>
      ) : (
        <p className="fp-empty">מקום מבודד — ללא חיבורים.</p>
      )}
    </FloatingPanel>
  );
}
