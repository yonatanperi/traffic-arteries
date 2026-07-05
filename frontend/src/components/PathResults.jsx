import { useState } from "react";
import { IconChevron, IconCopy, IconCheck } from "./icons.jsx";
import "./PathResults.css";

const ORDINALS = ["המסלול הקצר ביותר", "מסלול חלופי", "מסלול חלופי נוסף"];

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
      aria-label="העתק מסלול"
      title="העתק מסלול"
    >
      {copied ? <IconCheck size={15} /> : <IconCopy size={15} />}
      {copied ? "הועתק" : "העתק"}
    </button>
  );
}

export default function PathResults({ paths }) {
  return (
    <div className="results">
      {paths.map((path, i) => {
        const hops = path.length - 1;
        return (
          <article
            className="result-card"
            key={i}
            style={{ animationDelay: `${i * 70}ms` }}
          >
            <header className="result-head">
              <div className="result-meta">
                <h3 className="result-title">
                  {ORDINALS[i] || `מסלול ${i + 1}`}
                </h3>
                <span className="result-hops">
                  {path.length} תחנות · {hops} מקטעים
                </span>
              </div>
              <CopyButton path={path} />
            </header>

            <ol className="chain">
              {path.map((place, j) => (
                <li className="chain-item" key={j}>
                  <span
                    className={
                      "stop" +
                      (j === 0 ? " stop--start" : "") +
                      (j === path.length - 1 ? " stop--end" : "")
                    }
                  >
                    {place}
                  </span>
                  {j < path.length - 1 && (
                    <span className="chain-arrow" aria-hidden="true">
                      <IconChevron size={15} />
                    </span>
                  )}
                </li>
              ))}
            </ol>
          </article>
        );
      })}
    </div>
  );
}
