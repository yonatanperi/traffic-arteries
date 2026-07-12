import { useState } from "react";
import { IconCopy, IconCheck } from "../../ui/icons";
import { RouteChain } from "../../shared/RouteChain";
import Pill from "../../ui/Pill";
import { classifyPlace } from "../../../utils/placeTypes.js";
import "./PathResults.css";

const ORDINALS = ["הציר המיטבי", "ציר חלופי", "ציר חלופי נוסף"];

// "Best" rides one authored route as far as possible; surface how many routes it
// stitches and the match (concentration) score.
function mergeLabel(count) {
  if (!count) return null;
  return count === 1 ? "משלב ציר אחד" : `משלב ${count} צירים`;
}

// Start and end are always kept; only interior stops are subject to filtering.
function visiblePath(path, hiddenTypes) {
  if (!hiddenTypes || hiddenTypes.size === 0) return path;
  return path.filter((place, i) => {
    if (i === 0 || i === path.length - 1) return true;
    const type = classifyPlace(place);
    return !(type && hiddenTypes.has(type));
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
  return (
    <div className="results">
      {paths.map((path, i) => {
        const shown = visiblePath(path, hiddenTypes);
        const filtered = shown.length !== path.length;
        const info = meta?.[i];
        const merge = mergeLabel(info?.routeCount);
        const match = info?.match;

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
                <span>
                  {path.length} תחנות
                  {filtered && ` (${shown.length} מוצגות)`}
                </span>
              </span>

              {info?.routes?.length > 0 && (
                <div className="merge-routes">
                  <span className="merge-routes-label">צירים:</span>
                  {info.routes.map((r, j) => (
                    <Pill size="sm" className="merge-route-chip" key={j}>
                      {r.label}
                      {typeof r.share === "number" && (
                        <span className="merge-route-share">{r.share}%</span>
                      )}
                    </Pill>
                  ))}
                </div>
              )}
            </div>

            <RouteChain stops={shown} />
          </article>
        );
      })}
    </div>
  );
}
