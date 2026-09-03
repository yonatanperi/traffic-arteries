import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { IconCopy, IconCheck, IconRoute } from "../../ui/icons";
import {
  SegmentedRouteChain,
  visibleSegments,
  shownStops,
} from "../../shared/RouteChain";
import Pill from "../../ui/Pill";
import IconButton from "../../ui/IconButton";
import {
  isDowngraded,
  priorityLabel,
  priorityLetter,
} from "../../../utils/priorities.js";
import { useAuth } from "../../../hooks/useAuth.js";
import "./PathResults.css";

const ORDINALS = ["הציר המיטבי", "ציר חלופי", "ציר חלופי נוסף"];

// "Best" rides one authored route as far as possible; surface how many routes it
// stitches and the match (concentration) score.
function mergeLabel(count) {
  if (!count) return null;
  return count === 1 ? "משלב ציר אחד" : `משלב ${count} צירים`;
}

// `label` is built server-side as `${origin} - ${dest}` (the authored route's
// endpoints, see backend/api/views.py:run_meta) — split it back apart so it
// can feed the route editor's destination filter.
function splitLabel(label) {
  const i = label.indexOf(" - ");
  if (i === -1) return [label, label];
  return [label.slice(0, i), label.slice(i + 3)];
}

function CopyButton({ path }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    const text = path.join(", ");
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Fallback for browsers/contexts without the async clipboard API.
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  }

  return (
    <Pill
      as="button"
      size="md"
      className={"copy-btn" + (copied ? " copy-btn--done" : "")}
      onClick={copy}
      aria-label="העתק ציר"
      title="העתק ציר"
    >
      {copied ? <IconCheck size={15} /> : <IconCopy size={15} />}
      {copied ? "הועתק" : "העתק"}
    </Pill>
  );
}

export default function PathResults({ paths, meta, hiddenTypes }) {
  // { pathIndex, chipKey, startIndex, endIndex } | null. `chipKey` is the chip's
  // startIndex rather than its position in a list: sub-routes are disjoint
  // contiguous ranges, so it identifies the chip uniquely wherever the chip is
  // rendered — which matters now that the chips are split across segment headers.
  const [hovered, setHovered] = useState(null);
  const [pinned, setPinned] = useState(null); // same shape, set by click and sticky
  const navigate = useNavigate();
  const { role } = useAuth();
  const canEditRoutes = role === "editor" || role === "admin";

  function goToRoute(label) {
    const [origin, dest] = splitLabel(label);
    const params = new URLSearchParams();
    params.append("dest", origin);
    params.append("dest", dest);
    navigate(`/routes?${params.toString()}`);
  }

  // The sub-route chips for one stretch of a result. Rendered once for the whole
  // route when the trip has no required stops, and once per segment when it does —
  // the chips (and the shares on them) are scored per leg, so that is where they
  // belong.
  function renderChips(pathIndex, routes) {
    if (!routes?.length) return null;
    return (
      <div className="merge-routes">
        <span className="merge-routes-label">צירים:</span>
        {routes.map((r) => {
          const target = {
            pathIndex,
            chipKey: r.startIndex,
            startIndex: r.startIndex,
            endIndex: r.endIndex,
          };
          const isChipHovered =
            hovered?.pathIndex === pathIndex &&
            hovered?.chipKey === r.startIndex;
          const isChipPinned =
            pinned?.pathIndex === pathIndex && pinned?.chipKey === r.startIndex;
          return (
            <span className="merge-route-chip-group" key={r.startIndex}>
              <Pill
                as="button"
                size="sm"
                title={
                  isDowngraded(r.priority)
                    ? `ציר מקור ב${priorityLabel(r.priority)}`
                    : undefined
                }
                className={
                  "merge-route-chip" +
                  (isChipHovered || isChipPinned
                    ? " merge-route-chip--hovered"
                    : "") +
                  (isDowngraded(r.priority)
                    ? " merge-route-chip--downgraded"
                    : "")
                }
                onMouseEnter={() => setHovered(target)}
                onMouseLeave={() => setHovered(null)}
                onClick={() =>
                  setPinned((prev) =>
                    prev?.pathIndex === pathIndex &&
                    prev?.chipKey === r.startIndex
                      ? null
                      : target,
                  )
                }
              >
                {r.label}
                {isDowngraded(r.priority) && (
                  <span className="merge-route-priority">
                    {priorityLetter(r.priority)}
                  </span>
                )}
                {typeof r.share === "number" && (
                  <span className="merge-route-share">{r.share}%</span>
                )}
              </Pill>
              {isChipPinned && canEditRoutes && (
                <IconButton
                  size="sm"
                  info
                  className="merge-route-goto"
                  ariaLabel={`ערוך את הציר ${r.label} בעריכת צירים`}
                  title="ערוך ציר זה"
                  onClick={() => goToRoute(r.label)}
                >
                  <IconRoute size={13} />
                </IconButton>
              )}
            </span>
          );
        })}
      </div>
    );
  }

  // A segment's own stats. Each leg is planned and scored as its own route, so it
  // has its own match and tier — and because a leg's percentage is put on the
  // route's scale server-side, the route's match is exactly the length-weighted
  // mean of the numbers shown here rather than a fourth unrelated figure.
  function renderLegStats(pathIndex, leg) {
    return (
      <>
        {typeof leg?.match === "number" && (
          <Pill size="sm" className="match-badge">
            התאמה {leg.match}%
          </Pill>
        )}
        {isDowngraded(leg?.priority) && (
          <Pill
            size="sm"
            tone="warning"
            className="priority-badge"
            title="המקטע עובר בציר מקור בעדיפות נמוכה — לא נמצאה חלופה טובה יותר"
          >
            {priorityLabel(leg.priority)}
          </Pill>
        )}
        {renderChips(pathIndex, leg?.routes)}
      </>
    );
  }

  return (
    <div className="results">
      {paths.map((path, i) => {
        const info = meta?.[i];
        // The trip as it is actually drawn: one part per segment, with each
        // required stop raised onto a band between them. Without required stops
        // this is a single part holding the whole filtered chain.
        const parts = visibleSegments(path, info?.legs, hiddenTypes);
        const shown = shownStops(parts);
        const filtered = shown.length !== path.length;
        const segmented = parts.length > 1;
        const merge = mergeLabel(info?.routeCount);
        const match = info?.match;
        // Hovering a chip previews it even while another is pinned; once the
        // mouse leaves, the view falls back to whatever is pinned.
        const active =
          hovered?.pathIndex === i
            ? hovered
            : pinned?.pathIndex === i
              ? pinned
              : null;
        const highlightedStops = active
          ? new Set(path.slice(active.startIndex, active.endIndex + 1))
          : null;

        return (
          <article
            className={
              "card result-card" + (i === 0 ? " result-card--best" : "")
            }
            key={i}
            style={{ animationDelay: `${i * 70}ms` }}
          >
            <header className="result-head">
              <h3 className="result-title">{ORDINALS[i] || `ציר ${i + 1}`}</h3>
              <CopyButton path={shown} />
            </header>

            {canEditRoutes && (
              <div className="result-meta">
                <span className="result-hops">
                  {merge && (
                    <Pill size="sm" className="merge-badge">
                      {merge}
                    </Pill>
                  )}
                  {typeof match === "number" && (
                    <Pill size="sm" className="match-badge">
                      התאמה {match}%
                    </Pill>
                  )}
                  {/* Ranking puts the best priority tier first, so a longer route
                    can legitimately outrank a shorter one. Say so, or it reads
                    as a bug. */}
                  {isDowngraded(info?.priority) && (
                    <Pill
                      size="sm"
                      tone="warning"
                      className="priority-badge"
                      title="הציר עובר בציר מקור בעדיפות נמוכה — לא נמצאה חלופה טובה יותר"
                    >
                      {priorityLabel(info.priority)}
                    </Pill>
                  )}
                  <span>
                    {path.length} תחנות
                    {filtered && ` (${shown.length} מוצגות)`}
                  </span>
                </span>

                {/* Split trips carry their chips in the segment headers instead:
                    a sub-route belongs to the leg it was scored in, and its share
                    is a share of that leg. */}
                {!segmented && renderChips(i, info?.routes)}
              </div>
            )}

            <SegmentedRouteChain
              parts={parts}
              highlightedStops={highlightedStops}
              renderHeader={
                canEditRoutes ? (leg) => renderLegStats(i, leg) : undefined
              }
            />
          </article>
        );
      })}
    </div>
  );
}
