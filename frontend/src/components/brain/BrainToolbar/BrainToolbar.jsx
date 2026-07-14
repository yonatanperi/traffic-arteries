import { useMemo, useState } from "react";
import Autocomplete from "../../ui/Autocomplete";
import { SegmentedControl } from "../../ui/SegmentedControl";
import SwapButton from "../../ui/SwapButton";
import Pill from "../../ui/Pill";
import Button from "../../ui/Button";
import WaypointsField from "../../shared/WaypointsField";
import { useOriginDestination } from "../../../hooks/useOriginDestination.js";
import {
  IconSearch,
  IconFit,
  IconReset,
  IconPause,
  IconPlay,
  IconDownload,
  IconBulb,
  IconRoute,
  IconOrigin,
  IconDestination,
  IconClose,
  IconAlert,
  IconFocus,
} from "../../ui/icons";
import "./BrainToolbar.css";

const ORDINALS = ["המיטבי", "חלופי", "חלופי נוסף"];

// Compact label for a path chip. "Best" rides one authored route as far as
// possible, so prefer the match (concentration) score, falling back to the
// merge count and then the stop count.
function chipLabel(info, stopCount) {
  if (info?.match != null) return `התאמה ${info.match}%`;
  if (info?.routeCount) {
    return info.routeCount === 1 ? "ציר יחיד" : `${info.routeCount} צירים`;
  }
  return `${stopCount} תחנות`;
}

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
  vias,
  onAddVia,
  onSetVia,
  onRemoveVia,
  invalidPlaces,
}) {
  const [query, setQuery] = useState("");
  const { start, setStart, end, setEnd, swap } = useOriginDestination();

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

  function clearPath() {
    setStart("");
    setEnd("");
    onClearPath();
  }

  const paths = pathResult?.paths ?? null;
  const meta = pathResult?.meta ?? null;

  return (
    <div className="brain-toolbar">
      <SegmentedControl
        ariaLabel="מצב תצוגה"
        value={mode}
        onChange={onModeChange}
        className="bt-modes"
        items={[
          { value: "explore", icon: <IconSearch size={16} />, label: "חקירה" },
          { value: "path", icon: <IconRoute size={16} />, label: "ציר" },
        ]}
      />

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
            <Button
              variant="ghost"
              className="bt-icon"
              onClick={onZoomFit}
              title="התאם לתצוגה"
              aria-label="התאם לתצוגה"
            >
              <IconFit size={18} />
            </Button>
            <Button
              variant="ghost"
              className="bt-icon"
              onClick={onReset}
              title="סדר מחדש"
              aria-label="סדר מחדש"
            >
              <IconReset size={18} />
            </Button>
            <Button
              variant="ghost"
              className="bt-icon"
              onClick={onTogglePause}
              title={paused ? "המשך תנועה" : "השהה תנועה"}
              aria-label={paused ? "המשך תנועה" : "השהה תנועה"}
            >
              {paused ? <IconPlay size={18} /> : <IconPause size={18} />}
            </Button>
            <Button
              variant="ghost"
              className={"bt-icon" + (highlightDeadEnds ? " bt-icon--on" : "")}
              onClick={onToggleDeadEnds}
              title="הדגש קצוות מבודדים"
              aria-label="הדגש קצוות מבודדים"
              aria-pressed={highlightDeadEnds}
            >
              <IconAlert size={18} />
            </Button>
            <Button
              variant="ghost"
              className={"bt-icon" + (showInsights ? " bt-icon--on" : "")}
              onClick={onToggleInsights}
              title="תובנות על הרשת"
              aria-label="תובנות על הרשת"
              aria-pressed={showInsights}
            >
              <IconBulb size={18} />
            </Button>
            <Button
              variant="ghost"
              className="bt-icon"
              onClick={onExport}
              title="שמור כתמונה"
              aria-label="שמור כתמונה"
            >
              <IconDownload size={18} />
            </Button>
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
              invalid={invalidPlaces?.has(start.trim())}
            />
            <SwapButton onClick={swap} />
            <Autocomplete
              icon={<IconDestination size={17} />}
              placeholder="יעד"
              options={placeOptions}
              value={end}
              onChange={setEnd}
              invalid={invalidPlaces?.has(end.trim())}
            />
          </div>

          <div className="bt-path-waypoints">
            <WaypointsField
              places={placeOptions}
              vias={vias}
              onAddVia={onAddVia}
              onSetVia={onSetVia}
              onRemoveVia={onRemoveVia}
              invalidPlaces={invalidPlaces}
            />
          </div>

          <div className="bt-path-submit-and-meta">
            <Button
              size="sm"
              type="submit"
              variant="primary"
              className="bt-find"
              disabled={pathLoading}
            >
              <IconRoute size={17} />
              {pathLoading ? "מחשב…" : "הצג ציר"}
            </Button>

            {paths && paths.length > 0 && (
              <div className="bt-path-chips">
                {paths.map((p, i) => (
                  <Pill
                    as="button"
                    size="md"
                    key={i}
                    className={
                      "bt-chip" + (i === activePathIndex ? " bt-chip--on" : "")
                    }
                    onClick={() => onSelectPathIndex(i)}
                  >
                    {ORDINALS[i] || `ציר ${i + 1}`}
                    <span className="bt-chip-hops">
                      {chipLabel(meta?.[i], p.length)}
                    </span>
                  </Pill>
                ))}
                <Pill
                  as="button"
                  size="md"
                  className="bt-chip bt-chip--clear"
                  onClick={clearPath}
                  aria-label="נקה ציר"
                  title="נקה ציר"
                >
                  <IconClose size={15} />
                </Pill>
              </div>
            )}
          </div>

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
