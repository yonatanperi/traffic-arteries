import { useEffect } from "react";
import { createPortal } from "react-dom";
import { PLACE_GROUPS } from "../../../utils/placeGroups.js";
import "./PlaceGroupPopover.css";

/**
 * Asks which group a brand-new stop belongs to, when its typed text didn't
 * match any recognized prefix (see `EditableRouteChain`'s `commitEdit`) —
 * modeled on `RouteEditor/SelectionMenuPopover`'s interaction pattern (portal,
 * viewport-pinned, dismiss on outside click/Escape/scroll/resize).
 *
 * The picked group is used by the caller to *construct* the stop's final
 * text (`formatPlace(baseName, group)`) — this component only reports which
 * group was chosen, same division of responsibility as the priority popover.
 *
 * Unlike that popover, dismissal here is destructive (the caller reverts or
 * removes the stop) — so, deliberately, only a real "no" (outside click,
 * Escape) closes it. A scroll/resize doesn't: the caller repositions this
 * popover to follow its anchor instead, so an incidental scroll never reads
 * as "cancel" the way it would for an ordinary menu.
 *
 * props:
 *   at         { top, right } viewport coordinates to pin the card to
 *   baseName   the typed text that needs a group, shown in the prompt
 *   onPick     (groupKey) => void
 *   onClose    () => void — dismissed without picking (cancels the add/edit)
 */
export default function PlaceGroupPopover({ at, baseName, onPick, onClose }) {
  useEffect(() => {
    function onDocDown(e) {
      if (!e.target.closest?.(".place-group-pop")) onClose();
    }
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onDocDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return createPortal(
    <div
      className="place-group-pop"
      role="menu"
      aria-label={`לאיזו קבוצה שייך "${baseName}"?`}
      style={{ top: at.top, right: at.right }}
    >
      <p className="place-group-pop-title">לאיזו קבוצה שייך "{baseName}"?</p>
      {PLACE_GROUPS.map((group) => (
        <button
          key={group.key}
          type="button"
          role="menuitemradio"
          aria-checked={false}
          className="place-group-pop-item"
          onClick={() => onPick(group.key)}
        >
          {group.label}
        </button>
      ))}
    </div>,
    document.body,
  );
}
