import { useMemo, useState } from "react";
import Autocomplete from "../../ui/Autocomplete";
import ConfirmModal from "../../ui/ConfirmModal";
import { EditableRouteChain } from "../../shared/RouteChain";
import RemovableChip from "../../ui/RemovableChip";
import Pill from "../../ui/Pill";
import EditableList from "../../ui/EditableList";
import EditableGroupRow from "../../ui/EditableGroupRow";
import { IconSearch, IconAlert } from "../../ui/icons";
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
 *   compromisedPlaces  Set of destination names currently marked unavailable
 */
export default function RouteEditor({
  routes,
  onChange,
  suggestions,
  compromisedPlaces,
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState([]); // filter destinations (pills)
  const [pendingRename, setPendingRename] = useState(null); // { oldValue, newValue }

  function updateRoute(index, nextRoute) {
    const next = routes.slice();
    next[index] = nextRoute;
    onChange(next);
  }

  function addRoute() {
    onChange([...routes, []]);
  }

  function removeRoute(index) {
    onChange(routes.filter((_, i) => i !== index));
  }

  function addFilter(place) {
    const p = place.trim();
    if (!p) return;
    setSelected((s) => (s.includes(p) ? s : [...s, p]));
    setQuery("");
  }
  function removeFilter(place) {
    setSelected((s) => s.filter((x) => x !== place));
  }

  // A stop was renamed in one route. If that name appears elsewhere too, offer
  // to change every instance. The single edit has already been emitted, so the
  // still-current `routes` prop holds exactly one extra copy (the edited spot).
  function requestRename(oldValue, newValue) {
    if (oldValue === newValue) return;
    const total = routes.reduce(
      (n, r) => n + r.filter((p) => p === oldValue).length,
      0,
    );
    if (total - 1 > 0) setPendingRename({ oldValue, newValue });
  }
  function confirmRename() {
    const { oldValue, newValue } = pendingRename;
    setPendingRename(null);
    onChange(routes.map((r) => r.map((p) => (p === oldValue ? newValue : p))));
  }

  const { find, mainRoot, componentCount } = useMemo(
    () => analyzeConnectivity(routes),
    [routes],
  );

  const q = query.trim().toLowerCase();
  const terms = selected.map((s) => s.toLowerCase());
  const highlight = q ? [...terms, q] : terms;
  const filtering = selected.length > 0 || q;
  const visibleIndices = routes
    .map((_, i) => i)
    .filter((i) => {
      const route = routes[i];
      // Every selected destination must appear somewhere in the route (any
      // order), and the live-typed text further narrows the list.
      const hasAll = selected.every((s) =>
        route.some((p) => p.toLowerCase().includes(s.toLowerCase())),
      );
      const hasQuery = !q || route.some((p) => p.toLowerCase().includes(q));
      return hasAll && hasQuery;
    });

  return (
    <div className="editor">
      <div className="editor-search">
        <Autocomplete
          options={suggestions}
          value={query}
          onChange={setQuery}
          onSelect={addFilter}
          onSubmit={addFilter}
          icon={<IconSearch size={16} />}
          placeholder={selected.length ? "הוסף עוד…" : "סנן צירים לפי תחנות…"}
          prefix={
            selected.length
              ? selected.map((p) => (
                  // A pill styled like a route's start/end destination; clicking
                  // it removes the filter (no separate remove button).
                  <RemovableChip
                    key={p}
                    className="stop stop--start stop--filter"
                    onRemove={() => removeFilter(p)}
                    ariaLabel={`הסר ${p} מהסינון`}
                    title="הסר מהסינון"
                  >
                    {p}
                  </RemovableChip>
                ))
              : null
          }
        />
        {filtering && (
          <span className="editor-search-count">
            {visibleIndices.length
              ? `נמצאו ${visibleIndices.length} צירים`
              : "לא נמצאו צירים תואמים"}
          </span>
        )}
      </div>

      <EditableList onAdd={addRoute} addLabel="הוסף ציר חדש">
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
              highlight={highlight}
              disconnected={disconnected}
              compromisedPlaces={compromisedPlaces}
              onChangeRoute={(next) => updateRoute(i, next)}
              onRemoveRoute={() => removeRoute(i)}
              onRenameStop={requestRename}
            />
          );
        })}
      </EditableList>

      {pendingRename && (
        <ConfirmModal
          title="שינוי שם תחנה"
          message={`התחנה "${pendingRename.oldValue}" מופיעה בצירים נוספים. לשנות את כל המופעים ל"${pendingRename.newValue}"?`}
          confirmLabel="שנה בכל הצירים"
          cancelLabel="רק כאן"
          onConfirm={confirmRename}
          onCancel={() => setPendingRename(null)}
        />
      )}
    </div>
  );
}

function RouteRow({
  index,
  route,
  suggestions,
  highlight,
  disconnected,
  compromisedPlaces,
  onChangeRoute,
  onRemoveRoute,
  onRenameStop,
}) {
  const tooShort = route.length < 2;
  const hasCompromised = route.some((p) => compromisedPlaces?.has(p));
  const extraClassName = [
    disconnected && "route-row--disconnected",
    hasCompromised && "route-row--compromised",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <EditableGroupRow
      warn={tooShort}
      extraClassName={extraClassName || undefined}
      badge={
        route.length >= 2 && (
          <Pill size="sm" className="route-badge">
            {`${route[0]} - ${route[route.length - 1]}`}
          </Pill>
        )
      }
      warning={
        <>
          {tooShort && <span className="route-warn">דרושות לפחות שתי תחנות</span>}
          {!tooShort && disconnected && (
            <span className="route-warn route-warn--danger">
              <IconAlert size={14} /> ציר מנותק מהרשת הראשית
            </span>
          )}
          {!tooShort && hasCompromised && (
            <span className="route-warn route-warn--danger">
              <IconAlert size={14} /> כולל יעד מושבת
            </span>
          )}
        </>
      }
      onRemove={onRemoveRoute}
      removeLabel={`מחק ציר ${index + 1}`}
    >
      <EditableRouteChain
        stops={route}
        onChange={onChangeRoute}
        suggestions={suggestions}
        highlight={highlight}
        onRenameStop={onRenameStop}
        compromisedPlaces={compromisedPlaces}
      />
    </EditableGroupRow>
  );
}
