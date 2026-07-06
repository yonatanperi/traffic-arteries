import { useState } from "react";
import Autocomplete from "./Autocomplete.jsx";
import { IconPlus, IconClose, IconTrash } from "./icons.jsx";
import "./RouteEditor.css";

/**
 * Full editor for the routes list.
 *
 * props:
 *   routes     array of arrays of place names
 *   onChange   (nextRoutes) => void
 *   suggestions  list of known place names (feeds the add-stop dropdown)
 */
export default function RouteEditor({ routes, onChange, suggestions }) {
  function updateRoute(index, nextRoute) {
    const next = routes.slice();
    next[index] = nextRoute;
    onChange(next);
  }

  function removeStop(routeIndex, stopIndex) {
    updateRoute(
      routeIndex,
      routes[routeIndex].filter((_, i) => i !== stopIndex)
    );
  }

  function addStop(routeIndex, place) {
    updateRoute(routeIndex, [...routes[routeIndex], place]);
  }

  function addRoute() {
    onChange([...routes, []]);
  }

  function removeRoute(index) {
    onChange(routes.filter((_, i) => i !== index));
  }

  return (
    <div className="editor">
      <div className="editor-list">
        {routes.map((route, i) => (
          <RouteRow
            key={i}
            index={i}
            route={route}
            suggestions={suggestions}
            onRemoveStop={(s) => removeStop(i, s)}
            onAddStop={(p) => addStop(i, p)}
            onRemoveRoute={() => removeRoute(i)}
          />
        ))}
      </div>

      <button type="button" className="btn add-route-btn" onClick={addRoute}>
        <IconPlus size={16} /> הוסף מסלול חדש
      </button>
    </div>
  );
}

function RouteRow({
  index,
  route,
  suggestions,
  onRemoveStop,
  onAddStop,
  onRemoveRoute,
}) {
  const [draft, setDraft] = useState("");

  function commit(value) {
    const place = (value ?? draft).trim();
    if (!place) return;
    onAddStop(place);
    setDraft("");
  }

  const tooShort = route.length < 2;

  return (
    <div className={"route-row" + (tooShort ? " route-row--warn" : "")}>
      <div className="route-row-head">
        <span className="route-badge">מסלול {index + 1}</span>
        {tooShort && <span className="route-warn">דרושות לפחות שתי תחנות</span>}
        <button
          type="button"
          className="btn btn-danger route-remove"
          onClick={onRemoveRoute}
          aria-label={`מחק מסלול ${index + 1}`}
        >
          <IconTrash size={15} /> מחק
        </button>
      </div>

      <div className="stops">
        {route.map((place, j) => (
          <span className="chip" key={j}>
            <span className="chip-index">{j + 1}</span>
            {place}
            <button
              type="button"
              className="chip-remove"
              aria-label={`הסר את ${place}`}
              onClick={() => onRemoveStop(j)}
            >
              <IconClose size={13} />
            </button>
          </span>
        ))}

        <div className="add-stop">
          <Autocomplete
            options={suggestions}
            value={draft}
            onChange={setDraft}
            onSelect={commit}
            onSubmit={commit}
            placeholder={route.length ? "הוסף תחנה…" : "תחנה ראשונה…"}
          />
          <button
            type="button"
            className="add-stop-btn"
            onClick={() => commit()}
            disabled={!draft.trim()}
            aria-label="הוסף תחנה"
          >
            <IconPlus size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
