import { IconChevron } from "./icons.jsx";
import "./PathResults.css";

const ORDINALS = ["המסלול הקצר ביותר", "מסלול חלופי", "מסלול חלופי נוסף"];

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
