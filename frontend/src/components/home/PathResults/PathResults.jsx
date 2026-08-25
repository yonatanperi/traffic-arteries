import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { IconCopy, IconCheck, IconRoute } from "../../ui/icons";
import { RouteChain } from "../../shared/RouteChain";
import Pill from "../../ui/Pill";
import IconButton from "../../ui/IconButton";
import { classifyPlace, DEFAULT_GROUP } from "../../../utils/placeGroups.js";
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

// Start and end are always kept; only interior stops are subject to filtering.
// "אחר" is never hidden, regardless of hiddenTypes' contents — it has no
// filter chip to toggle it off in the first place (ResultsArea.jsx).
function visiblePath(path, hiddenTypes) {
  if (!hiddenTypes || hiddenTypes.size === 0) return path;
  return path.filter((place, i) => {
    if (i === 0 || i === path.length - 1) return true;
    const type = classifyPlace(place);
    return type === DEFAULT_GROUP || !hiddenTypes.has(type);
  });
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
  const [hovered, setHovered] = useState(null); // { pathIndex, chipIndex, startIndex, endIndex } | null
  const [pinned, setPinned] = useState(null); // same shape as hovered, but set by click and sticky
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

  return (
    <div className="results">
      {paths.map((path, i) => {
        const shown = visiblePath(path, hiddenTypes);
        const filtered = shown.length !== path.length;
        const info = meta?.[i];
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

                {info?.routes?.length > 0 && (
                  <div className="merge-routes">
                    <span className="merge-routes-label">צירים:</span>
                    {info.routes.map((r, j) => {
                      const isChipHovered =
                        hovered?.pathIndex === i && hovered?.chipIndex === j;
                      const isChipPinned =
                        pinned?.pathIndex === i && pinned?.chipIndex === j;
                      return (
                        <span className="merge-route-chip-group" key={j}>
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
                            onMouseEnter={() =>
                              setHovered({
                                pathIndex: i,
                                chipIndex: j,
                                startIndex: r.startIndex,
                                endIndex: r.endIndex,
                              })
                            }
                            onMouseLeave={() => setHovered(null)}
                            onClick={() =>
                              setPinned((prev) =>
                                prev?.pathIndex === i && prev?.chipIndex === j
                                  ? null
                                  : {
                                      pathIndex: i,
                                      chipIndex: j,
                                      startIndex: r.startIndex,
                                      endIndex: r.endIndex,
                                    },
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
                              <span className="merge-route-share">
                                {r.share}%
                              </span>
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
                )}
              </div>
            )}

            <RouteChain stops={shown} highlightedStops={highlightedStops} />
          </article>
        );
      })}
    </div>
  );
}
