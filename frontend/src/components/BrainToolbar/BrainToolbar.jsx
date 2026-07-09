import { useMemo, useState } from "react";
import Autocomplete from "../Autocomplete";
import {
  IconSearch,
  IconFocus,
  IconFit,
  IconReset,
  IconPause,
  IconPlay,
  IconDownload,
  IconBulb,
  IconRoute,
  IconOrigin,
  IconDestination,
  IconSwap,
  IconClose,
  IconAlert,
} from "../icons";
import "./BrainToolbar.css";

const ORDINALS = ["הקצר ביותר", "חלופי", "חלופי נוסף"];

/**
 * The control strip above the brain canvas. Two modes:
 *   - "explore": search a place + canvas controls (fit / reset / pause /
 *     dead-ends / insights / export).
 *   - "path": pick origin + destination, find routes, and switch between the
 *     highlighted alternatives.
 *
 * Interactive inputs live here (outside the canvas); read-only panels float
 * over the canvas and are owned by the page.
 */
export default function BrainToolbar({
  mode,
  onModeChange,
  placeOptions,
  // explore
  onFocusNode,
  onZoomFit,
  onReset,
  paused,
  onTogglePause,
  highlightDeadEnds,
  onToggleDeadEnds,
  showInsights,
  onToggleInsights,
  onExport,
  // path
  onSubmitPath,
  onClearPath,
  onSelectPathIndex,
  pathLoading,
  pathError,
  pathResult,
  activePathIndex,
}) {
  const [query, setQuery] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const placeSet = useMemo(() => new Set(placeOptions), [placeOptions]);

  function onSearchChange(value) {
    setQuery(value);
    if (placeSet.has(value)) onFocusNode(value);
  }

  function submitPath(e) {
    e.preventDefault();
    if (!start.trim() || !end.trim()) return;
    onSubmitPath(start.trim(), end.trim());
  }

  function swap() {
    setStart(end);
    setEnd(start);
  }

  function clearPath() {
    setStart("");
    setEnd("");
    onClearPath();
  }

  const paths = pathResult?.paths ?? null;

  return (
    <div className="brain-toolbar">
      <div className="bt-modes" role="tablist" aria-label="מצב תצוגה">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "explore"}
          className={"bt-mode" + (mode === "explore" ? " bt-mode--on" : "")}
          onClick={() => onModeChange("explore")}
        >
          <IconSearch size={16} />
          חקירה
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "path"}
          className={"bt-mode" + (mode === "path" ? " bt-mode--on" : "")}
          onClick={() => onModeChange("path")}
        >
          <IconRoute size={16} />
          ציר
        </button>
      </div>

      {mode === "explore" && (
        <div className="bt-explore">
          <div className="bt-search">
            <Autocomplete
              icon={<IconFocus size={17} />}
              placeholder="חיפוש מקום…"
              options={placeOptions}
              value={query}
              onChange={onSearchChange}
            />
          </div>

          <div className="bt-controls">
            <button
              type="button"
              className="btn btn-ghost bt-icon"
              onClick={onZoomFit}
              title="התאם לתצוגה"
              aria-label="התאם לתצוגה"
            >
              <IconFit size={18} />
            </button>
            <button
              type="button"
              className="btn btn-ghost bt-icon"
              onClick={onReset}
              title="סדר מחדש"
              aria-label="סדר מחדש"
            >
              <IconReset size={18} />
            </button>
            <button
              type="button"
              className="btn btn-ghost bt-icon"
              onClick={onTogglePause}
              title={paused ? "המשך תנועה" : "השהה תנועה"}
              aria-label={paused ? "המשך תנועה" : "השהה תנועה"}
            >
              {paused ? <IconPlay size={18} /> : <IconPause size={18} />}
            </button>
            <button
              type="button"
              className={
                "btn btn-ghost bt-icon" +
                (highlightDeadEnds ? " bt-icon--on" : "")
              }
              onClick={onToggleDeadEnds}
              title="הדגש קצוות מבודדים"
              aria-label="הדגש קצוות מבודדים"
              aria-pressed={highlightDeadEnds}
            >
              <IconAlert size={18} />
            </button>
            <button
              type="button"
              className={
                "btn btn-ghost bt-icon" + (showInsights ? " bt-icon--on" : "")
              }
              onClick={onToggleInsights}
              title="תובנות על הרשת"
              aria-label="תובנות על הרשת"
              aria-pressed={showInsights}
            >
              <IconBulb size={18} />
            </button>
            <button
              type="button"
              className="btn btn-ghost bt-icon"
              onClick={onExport}
              title="שמור כתמונה"
              aria-label="שמור כתמונה"
            >
              <IconDownload size={18} />
            </button>
          </div>
        </div>
      )}

      {mode === "path" && (
        <form className="bt-path" onSubmit={submitPath}>
          <div className="bt-path-fields">
            <Autocomplete
              icon={<IconOrigin size={17} />}
              placeholder="מוצא"
              options={placeOptions}
              value={start}
              onChange={setStart}
            />
            <button
              type="button"
              className="swap-btn"
              onClick={swap}
              aria-label="החלף מוצא ויעד"
              title="החלף מוצא ויעד"
            >
              <IconSwap size={18} />
            </button>
            <Autocomplete
              icon={<IconDestination size={17} />}
              placeholder="יעד"
              options={placeOptions}
              value={end}
              onChange={setEnd}
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary bt-find"
            disabled={pathLoading}
          >
            <IconRoute size={17} />
            {pathLoading ? "מחשב…" : "הצג ציר"}
          </button>

          {paths && paths.length > 0 && (
            <div className="bt-path-chips">
              {paths.map((p, i) => (
                <button
                  key={i}
                  type="button"
                  className={
                    "bt-chip" + (i === activePathIndex ? " bt-chip--on" : "")
                  }
                  onClick={() => onSelectPathIndex(i)}
                >
                  {ORDINALS[i] || `ציר ${i + 1}`}
                  <span className="bt-chip-hops">{p.length} תחנות</span>
                </button>
              ))}
              <button
                type="button"
                className="bt-chip bt-chip--clear"
                onClick={clearPath}
                aria-label="נקה ציר"
                title="נקה ציר"
              >
                <IconClose size={15} />
              </button>
            </div>
          )}

          {pathError && (
            <p className="bt-path-error" role="alert">
              {pathError}
            </p>
          )}
          {paths && paths.length === 0 && !pathError && (
            <p className="bt-path-error" role="status">
              אין ציר מחבר בין הנקודות.
            </p>
          )}
        </form>
      )}
    </div>
  );
}
