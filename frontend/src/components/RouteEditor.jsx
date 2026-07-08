import { useMemo, useState } from "react";
import Autocomplete from "./Autocomplete.jsx";
import {
  IconPlus,
  IconClose,
  IconTrash,
  IconSearch,
  IconAlert,
} from "./icons.jsx";
import "./RouteEditor.css";

/**
 * Groups every stop into connected components using the routes as edges
 * (consecutive stops within a route are linked in both directions). Returns
 * a `componentOf` lookup plus the id of the largest ("main") component, so
 * callers can flag routes that live on an island disconnected from it.
 */
function analyzeConnectivity(routes) {
  const parent = new Map();

  function find(place) {
    if (!parent.has(place)) parent.set(place, place);
    let root = place;
    while (parent.get(root) !== root) root = parent.get(root);
    let cur = place;
    while (cur !== root) {
      const next = parent.get(cur);
      parent.set(cur, root);
      cur = next;
    }
    return root;
  }

  function union(a, b) {
    const ra = find(a);
    const rb = find(b);
    if (ra !== rb) parent.set(ra, rb);
  }

  routes.forEach((route) => {
    route.forEach((place) => find(place));
    for (let i = 1; i < route.length; i++) {
      union(route[i - 1], route[i]);
    }
  });

  const sizeByRoot = new Map();
  for (const place of parent.keys()) {
    const root = find(place);
    sizeByRoot.set(root, (sizeByRoot.get(root) || 0) + 1);
  }

  let mainRoot = null;
  let mainSize = -1;
  for (const [root, size] of sizeByRoot) {
    if (size > mainSize) {
      mainSize = size;
      mainRoot = root;
    }
  }

  return { find, mainRoot, componentCount: sizeByRoot.size };
}

/**
 * Full editor for the routes list.
 *
 * props:
 *   routes     array of arrays of place names
 *   onChange   (nextRoutes) => void
 *   suggestions  list of known place names (feeds the add-stop dropdown)
 */
export default function RouteEditor({ routes, onChange, suggestions }) {
  const [search, setSearch] = useState("");

  function updateRoute(index, nextRoute) {
    const next = routes.slice();
    next[index] = nextRoute;
    onChange(next);
  }

  function removeStop(routeIndex, stopIndex) {
    updateRoute(
      routeIndex,
      routes[routeIndex].filter((_, i) => i !== stopIndex),
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

  const { find, mainRoot, componentCount } = useMemo(
    () => analyzeConnectivity(routes),
    [routes],
  );

  const query = search.trim().toLowerCase();
  const visibleIndices = routes
    .map((_, i) => i)
    .filter(
      (i) => !query || routes[i].some((p) => p.toLowerCase().includes(query)),
    );

  return (
    <div className="editor">
      <div className="editor-search">
        <Autocomplete
          options={suggestions}
          value={search}
          onChange={setSearch}
          icon={<IconSearch size={16} />}
          placeholder="חפש תחנה בצירים…"
        />
        {query && (
          <span className="editor-search-count">
            {visibleIndices.length
              ? `נמצאו ${visibleIndices.length} צירים`
              : "לא נמצאו צירים תואמים"}
          </span>
        )}
      </div>

      <div className="editor-list">
        {visibleIndices.map((i) => {
          const route = routes[i];
          const disconnected =
            componentCount > 1 &&
            route.length > 0 &&
            find(route[0]) !== mainRoot;
          return (
            <RouteRow
              key={i}
              index={i}
              route={route}
              suggestions={suggestions}
              highlight={query}
              disconnected={disconnected}
              onRemoveStop={(s) => removeStop(i, s)}
              onAddStop={(p) => addStop(i, p)}
              onRemoveRoute={() => removeRoute(i)}
            />
          );
        })}
      </div>

      <button type="button" className="btn add-route-btn" onClick={addRoute}>
        <IconPlus size={16} /> הוסף ציר חדש
      </button>
    </div>
  );
}

function RouteRow({
  index,
  route,
  suggestions,
  highlight,
  disconnected,
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
    <div
      className={
        "route-row" +
        (tooShort ? " route-row--warn" : "") +
        (disconnected ? " route-row--disconnected" : "")
      }
    >
      <div className="route-row-head">
        {route.length >= 2 && (
          <span className="route-badge">
            {`${route[0]} - ${route[route.length - 1]}`}
          </span>
        )}
        {tooShort && <span className="route-warn">דרושות לפחות שתי תחנות</span>}
        {!tooShort && disconnected && (
          <span className="route-warn route-warn--danger">
            <IconAlert size={14} /> ציר מנותק מהרשת הראשית
          </span>
        )}
        <button
          type="button"
          className="btn btn-danger route-remove"
          onClick={onRemoveRoute}
          aria-label={`מחק ציר ${index + 1}`}
        >
          <IconTrash size={15} /> מחק
        </button>
      </div>

      <div className="stops">
        {route.map((place, j) => {
          const matched = highlight && place.toLowerCase().includes(highlight);
          return (
            <span className={"chip" + (matched ? " chip--match" : "")} key={j}>
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
          );
        })}

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
