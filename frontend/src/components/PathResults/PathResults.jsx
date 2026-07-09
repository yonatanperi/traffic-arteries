import { useState } from "react";
import { IconCopy, IconCheck } from "./icons.jsx";
import { RouteChain } from "./RouteChain";
import { classifyPlace } from "../utils/placeTypes.js";
import "./PathResults.css";

const ORDINALS = ["הציר הקצר ביותר", "ציר חלופי", "ציר חלופי נוסף"];

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
    <button
      type="button"
      className={"copy-btn" + (copied ? " copy-btn--done" : "")}
      onClick={copy}
      aria-label="העתק ציר"
      title="העתק ציר"
    >
      {copied ? <IconCheck size={15} /> : <IconCopy size={15} />}
      {copied ? "הועתק" : "העתק"}
    </button>
  );
}

export default function PathResults({ paths, hiddenTypes }) {
  return (
    <div className="results">
      {paths.map((path, i) => {
        const shown = visiblePath(path, hiddenTypes);
        const filtered = shown.length !== path.length;
        return (
          <article
            className="result-card"
            key={i}
            style={{ animationDelay: `${i * 70}ms` }}
          >
            <header className="result-head">
              <div className="result-meta">
                <h3 className="result-title">
                  {ORDINALS[i] || `ציר ${i + 1}`}
                </h3>
                <span className="result-hops">
                  {path.length} תחנות
                  {filtered && ` (${shown.length} מוצגות)`}
                </span>
              </div>
              <CopyButton path={path} />
            </header>

            <RouteChain stops={shown} />
          </article>
        );
      })}
    </div>
  );
}
