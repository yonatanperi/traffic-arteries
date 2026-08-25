import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { PriorityOption } from "./PriorityDot";
import { PRIORITY_OPTIONS, BEST_PRIORITY } from "../../../utils/priorities.js";
import { IconArrowBack, IconChevron, IconDuplicate, IconTrash } from "../../ui/icons";
import "./SelectionMenuPopover.css";

/**
 * The one place a swept range of stops turns into something: it opens over the
 * stretch the author has just picked out, and offers everything that stretch can
 * become — a priority rating, a new route copied out of it, or its stops gone.
 *
 * Two faces, not one flat list: the root offers the three things a range can
 * become, and "שנה עדיפות" drills into the rating ramp (the original mechanism,
 * unchanged) rather than dumping all four priorities in among two one-shot
 * actions. `view` is local — the caller only needs the *outcome* of a pick, not
 * which screen got it there — and always starts back at the root, since the
 * parent only renders this popover while a range is pending (a fresh range is a
 * fresh mount).
 *
 * There is deliberately no priority picker anywhere else. A priority applies to a
 * *range* — a result pays for it only by riding the whole marked stretch — so
 * choosing one without a range in hand would be stating a rating with nothing to
 * attach it to. The other two actions ride the same range for the same reason:
 * "which stops" has to be answered before "do what to them" means anything.
 *
 * The best priority is what an unmarked stretch already rides at, so picking it
 * *clears* the range rather than marking it: that is the only "un-rate this" the
 * ramp needs, and it keeps the four options reading as one ordered scale.
 *
 * props:
 *   at             { top, right } viewport coordinates to pin the card to (RTL:
 *                  the start edge is the right one), from the stop the sweep ended on
 *   currentPriority  the priority already on this exact range, or BEST_PRIORITY
 *   onPickPriority (0..3) => void
 *   onCreateRoute  () => void — copy the range's stops into a brand-new route
 *   onDeleteStops  () => void — remove the range's stops from this route
 *   onClose        () => void
 */
export default function SelectionMenuPopover({
  at,
  currentPriority = BEST_PRIORITY,
  onPickPriority,
  onCreateRoute,
  onDeleteStops,
  onClose,
}) {
  const [view, setView] = useState("root"); // "root" | "priority"

  // Same dismissal rules as the chain's insert menu: an outside press, Escape, or
  // any scroll/resize, which would leave a fixed card stranded from its stops.
  useEffect(() => {
    function onDocDown(e) {
      if (!e.target.closest?.(".mark-pop")) onClose();
    }
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onDocDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onClose, true);
    window.addEventListener("resize", onClose);
    return () => {
      document.removeEventListener("mousedown", onDocDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onClose, true);
      window.removeEventListener("resize", onClose);
    };
  }, [onClose]);

  return createPortal(
    <div
      className="mark-pop"
      role="menu"
      aria-label={view === "root" ? "פעולות על הטווח הנבחר" : "עדיפות הטווח"}
      style={{ top: at.top, right: at.right }}
    >
      {view === "root" ? (
        <>
          <button
            type="button"
            role="menuitem"
            className="mark-pop-item"
            onClick={() => setView("priority")}
          >
            <span className="mark-pop-item-label">שנה עדיפות</span>
            <IconChevron size={13} className="mark-pop-item-arrow" />
          </button>
          <button
            type="button"
            role="menuitem"
            className="mark-pop-item"
            onClick={onCreateRoute}
          >
            <IconDuplicate size={15} /> צור ציר חדש מהבחירה
          </button>
          <button
            type="button"
            role="menuitem"
            className="mark-pop-item mark-pop-item--danger"
            onClick={onDeleteStops}
          >
            <IconTrash size={15} /> מחק תחנות
          </button>
        </>
      ) : (
        <>
          <button
            type="button"
            className="mark-pop-item mark-pop-back"
            onClick={() => setView("root")}
          >
            <IconArrowBack size={14} /> חזרה
          </button>
          {PRIORITY_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              role="menuitemradio"
              aria-checked={option.value === currentPriority}
              className={
                "mark-pop-item" +
                (option.value === currentPriority ? " mark-pop-item--on" : "")
              }
              onClick={() => onPickPriority(option.value)}
            >
              <PriorityOption option={option} />
            </button>
          ))}
        </>
      )}
    </div>,
    document.body,
  );
}
