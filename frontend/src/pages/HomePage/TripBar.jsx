import IconButton from "../../components/ui/IconButton";
import { IconArrowBack, IconChevron } from "../../components/ui/icons";

/**
 * The search form folded down to what you actually searched for — phones only
 * (HomePage decides), shown in place of the header + form once results exist so
 * the results own the screen. It is the one element pinned to the top of the
 * viewport, so the route stays legible the whole way down a results list.
 *
 * The whole summary is the way back into the form; the arrow is the same
 * action, placed where a phone's back affordance is expected.
 */
export default function TripBar({ start, end, vias, onEdit }) {
  const stops = vias.map((v) => v.trim()).filter(Boolean);
  // The stops are the one search parameter the folded bar would otherwise hide.
  const detail =
    stops.length > 0 ? `דרך: ${stops.join(", ")}` : "ללא עצירות ביניים";

  return (
    <div className="trip-bar">
      <IconButton
        size="lg"
        className="trip-bar-back"
        ariaLabel="חזרה לחיפוש"
        onClick={onEdit}
      >
        <IconArrowBack size={20} />
      </IconButton>

      <button
        type="button"
        className="trip-bar-summary"
        onClick={onEdit}
        aria-expanded={false}
      >
        <span className="trip-bar-text">
          <span className="trip-bar-route">
            <span className="trip-bar-place">{start}</span>
            <IconChevron size={14} className="trip-bar-arrow" />
            <span className="trip-bar-place">{end}</span>
          </span>
          <span className="trip-bar-detail">{detail}</span>
        </span>
        <IconChevron size={18} className="trip-bar-caret" />
      </button>
    </div>
  );
}
