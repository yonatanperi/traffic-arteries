import "./IdleBanner.css";

/**
 * The home page's idle state — shown before any search has run.
 *
 * Replaces the generic <EmptyState> here specifically: this is the first thing
 * anyone sees on the app, so it gets a bespoke "route scanner" visual (a radar
 * sweep over concentric rings, with a route drawing itself across it) instead
 * of a dashed empty box. The generic EmptyState is still the right component
 * for the "no route found" case, which is a real result, not an invitation.
 *
 * The whole visual is decorative and aria-hidden; the title and message carry
 * the meaning.
 */
export default function IdleBanner() {
  return (
    <div className="idle-banner">
      <div className="idle-visual" aria-hidden="true">
        <span className="idle-sweep" />
        <span className="idle-ring idle-ring--1" />
        <span className="idle-ring idle-ring--2" />
        <span className="idle-ring idle-ring--3" />

        <svg className="idle-trace" viewBox="0 0 200 200" role="presentation">
          {/* A route across the scope: origin, two interchanges, destination. */}
          <polyline
            className="idle-trace-line"
            points="46,132 84,96 120,110 154,68"
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <circle className="idle-node idle-node--start" cx="46" cy="132" r="5" />
          <circle className="idle-node idle-node--mid" cx="84" cy="96" r="3" />
          <circle className="idle-node idle-node--mid" cx="120" cy="110" r="3" />
          <circle className="idle-node idle-node--end" cx="154" cy="68" r="5" />
        </svg>
      </div>

      <h3 className="idle-title">מוכנים לצאת לדרך</h3>
      <p className="idle-message">
        הזינו שתי נקודות למעלה כדי לגלות את הצירים האפשריים ביניהן.
      </p>
    </div>
  );
}
