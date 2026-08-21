import { useEffect } from "react";
import { createPortal } from "react-dom";
import { PriorityOption } from "./PriorityDot";
import { PRIORITY_OPTIONS, BEST_PRIORITY } from "../../../utils/priorities.js";
import "./PriorityMarkPopover.css";

/**
 * The one place a priority is chosen: it opens over a stretch of stops the author
 * has just swept out, and rates that stretch.
 *
 * There is deliberately no picker anywhere else. A priority applies to a *range* —
 * a result pays for it only by riding the whole marked stretch — so choosing one
 * without a range in hand would be stating a rating with nothing to attach it to.
 *
 * The best priority is what an unmarked stretch already rides at, so picking it
 * *clears* the range rather than marking it: that is the only "un-rate this" the
 * list needs, and it keeps the four options reading as one ordered ramp.
 *
 * props:
 *   at         { top, right } viewport coordinates to pin the card to (RTL: the
 *              start edge is the right one), from the stop the sweep ended on
 *   current    the priority already on this exact range, or BEST_PRIORITY
 *   wholeLabel caption for the "widen to the whole segment" shortcut
 *   onPick     (0..3) => void
 *   onWhole    () => void — widen the pending range to the whole chain, list open
 *   onClose    () => void
 */
export default function PriorityMarkPopover({
  at,
  current = BEST_PRIORITY,
  wholeLabel,
  onPick,
  onWhole,
  onClose,
}) {
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
      aria-label="עדיפות הטווח"
      style={{ top: at.top, right: at.right }}
    >
      {PRIORITY_OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          role="menuitemradio"
          aria-checked={option.value === current}
          className={
            "mark-pop-item" +
            (option.value === current ? " mark-pop-item--on" : "")
          }
          onClick={() => onPick(option.value)}
        >
          <PriorityOption option={option} />
        </button>
      ))}
      <button
        type="button"
        role="menuitem"
        className="mark-pop-item mark-pop-whole"
        onClick={onWhole}
      >
        {wholeLabel}
      </button>
    </div>,
    document.body,
  );
}
