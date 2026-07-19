import { useEffect, useMemo, useState } from "react";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
  arrayMove,
} from "@dnd-kit/sortable";
import Autocomplete from "../../ui/Autocomplete";
import ConfirmModal from "../../ui/ConfirmModal";
import RemovableChip from "../../ui/RemovableChip";
import Pill from "../../ui/Pill";
import IconButton from "../../ui/IconButton";
import EditableList from "../../ui/EditableList";
import EditableGroupRow from "../../ui/EditableGroupRow";
import Select from "../../ui/Select";
import BranchedChain from "./BranchedChain";
import {
  IconSearch,
  IconAlert,
  IconDuplicate,
  IconPin,
  IconBranch,
} from "../../ui/icons";
import {
  expandRoute,
  routeStops,
  cloneRoute,
  renameStop,
  leafCount,
} from "../../../utils/branches.js";
import {
  useGetUrlParams,
  useSetUrlParams,
} from "../../../hooks/useUrlParams.js";
import {
  BEST_PRIORITY,
  PRIORITY_OPTIONS,
  isDowngraded,
} from "../../../utils/priorities.js";
import "./RouteEditor.css";

// Anything inside a route card that owns the pointer: the stop pills (they have
// their own drag), every control, and the inline editors. A press that starts on
// one of these must not turn into a card drag.
// `.sel` covers the priority dropdown's *options* too: they render inside the card,
// and the drag sensor fires on pointerdown — before the option's own mousedown.
// `.branched-viewport` is the branched tree's pan/zoom map: a drag there pans the
// canvas, so it must not also drag the whole card. (The card can still be reordered
// by dragging its header/padding, outside the map.)
const NO_ROW_DRAG =
  "button, input, a, .stop, .stop-edit, .ac, .sel, .branched-viewport";

// Per-row view state that `routes` itself can't carry: routes.json is a plain
// array of arrays, with no id to key a React element, a drag item or a pin by.
// It's kept as an array parallel to `routes`, and every structural edit applies
// the same splice/move to both — so a row's identity and its pin follow it.
let rowUid = 0;
const newRow = () => ({ id: `row-${rowUid++}`, pinned: false });

/**
 * The whole card is the drag handle (no separate grip button), so the sensor —
 * not a handle's listeners — is what keeps the card's insides usable: it simply
 * declines to activate when the press lands on an interactive descendant.
 */
class RowPointerSensor extends PointerSensor {
  static activators = [
    {
      eventName: "onPointerDown",
      handler: ({ nativeEvent: event }) => {
        if (!event.isPrimary || event.button !== 0) return false;
        return !event.target.closest?.(NO_ROW_DRAG);
      },
    },
  ];
}

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

  // A branched route contributes every subroute's edges (a branch connects into
  // the trunk), so expand each route to its chains before unioning.
  routes.forEach((route) => {
    expandRoute(route).forEach((places) => {
      places.forEach((place) => find(place));
      for (let i = 1; i < places.length; i++) {
        union(places[i - 1], places[i]);
      }
    });
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
 *   routes     array of { places: [place names], priority: 0..3 } (0 = best)
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
  const { getParam } = useGetUrlParams();
  const { setParams } = useSetUrlParams();
  const query = getParam("q");
  const selected = getParam("dest", { list: true }); // filter destinations (pills)
  function setQuery(value) {
    setParams({ q: value });
  }
  const [pendingRename, setPendingRename] = useState(null); // { oldValue, newValue }

  const [rows, setRows] = useState(() => routes.map(newRow));
  // Only ever re-synced if `routes` changes length behind our back (it doesn't
  // today — every add/remove goes through this component); a guard, not a path.
  useEffect(() => {
    setRows((prev) =>
      prev.length === routes.length
        ? prev
        : routes.map((_, i) => prev[i] ?? newRow()),
    );
  }, [routes.length]);

  // Every route edit is a patch onto the route object, so the fields the edit
  // doesn't touch (notably the priority) ride along untouched.
  function patchRoute(index, patch) {
    const next = routes.slice();
    next[index] = { ...routes[index], ...patch };
    onChange(next);
  }

  function addRoute() {
    onChange([...routes, { places: [], priority: BEST_PRIORITY }]);
    // A brand-new route is empty, so it matches no filter — pin it while one is
    // active, otherwise it would be added straight into hiding.
    setRows((prev) => [...prev, { ...newRow(), pinned: Boolean(filtering) }]);
  }

  function duplicateRoute(index) {
    const next = routes.slice();
    next.splice(index + 1, 0, cloneRoute(routes[index]));
    onChange(next);
    setRows((prev) => {
      const nextRows = prev.slice();
      nextRows.splice(index + 1, 0, {
        ...newRow(),
        pinned: prev[index].pinned,
      });
      return nextRows;
    });
  }

  function removeRoute(index) {
    onChange(routes.filter((_, i) => i !== index));
    setRows((prev) => prev.filter((_, i) => i !== index));
  }

  function togglePin(index) {
    setRows((prev) =>
      prev.map((row, i) =>
        i === index ? { ...row, pinned: !row.pinned } : row,
      ),
    );
  }

  function reorderRoutes(from, to) {
    onChange(arrayMove(routes, from, to));
    setRows((prev) => arrayMove(prev, from, to));
  }

  function addFilter(place) {
    const p = place.trim();
    if (!p) return;
    setParams({
      dest: selected.includes(p) ? selected : [...selected, p],
      q: null,
    });
  }
  function removeFilter(place) {
    setParams({ dest: selected.filter((x) => x !== place) });
  }

  // A stop was renamed in one route. If that name appears elsewhere too, offer
  // to change every instance. The single edit has already been emitted, so the
  // still-current `routes` prop holds exactly one extra copy (the edited spot).
  function requestRename(oldValue, newValue) {
    if (oldValue === newValue) return;
    const total = routes.reduce(
      (n, r) => n + routeStops(r).filter((p) => p === oldValue).length,
      0,
    );
    if (total - 1 > 0) setPendingRename({ oldValue, newValue });
  }
  function confirmRename() {
    const { oldValue, newValue } = pendingRename;
    setPendingRename(null);
    onChange(routes.map((r) => renameStop(r, oldValue, newValue)));
  }

  const { find, mainRoot, componentCount } = useMemo(
    () => analyzeConnectivity(routes),
    [routes],
  );

  const q = query.trim().toLowerCase();
  const terms = selected.map((s) => s.toLowerCase());
  const highlight = q ? [...terms, q] : terms;
  const filtering = selected.length > 0 || q;

  const matchedIndices = routes
    .map((_, i) => i)
    .filter((i) => {
      const { places } = routes[i];
      // Every selected destination must appear somewhere in the route (any
      // order), and the live-typed text further narrows the list.
      const hasAll = selected.every((s) =>
        places.some((p) => p.toLowerCase().includes(s.toLowerCase())),
      );
      const hasQuery = !q || places.some((p) => p.toLowerCase().includes(q));
      return hasAll && hasQuery;
    });

  // Pinned routes ride through the filter — they stay listed (in place) even
  // when they don't match, so a route you're working on can't be filtered away.
  const matched = new Set(matchedIndices);
  const visibleIndices = routes
    .map((_, i) => i)
    // `rows[i] &&`: should a `routes` update ever land before the row-state sync
    // effect catches up, skip the row for that one render rather than throwing.
    .filter((i) => rows[i] && (matched.has(i) || rows[i].pinned));

  const sensors = useSensors(
    useSensor(RowPointerSensor, { activationConstraint: { distance: 8 } }),
  );

  function handleDragEnd({ active, over }) {
    if (!over || active.id === over.id) return;
    // Positions in the *full* list, so a drop made while the list is filtered
    // still lands the route exactly where it was dropped among all routes.
    const from = rows.findIndex((r) => r.id === active.id);
    const to = rows.findIndex((r) => r.id === over.id);
    if (from !== -1 && to !== -1) reorderRoutes(from, to);
  }

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
            {matchedIndices.length
              ? `נמצאו ${matchedIndices.length} צירים`
              : "לא נמצאו צירים תואמים"}
          </span>
        )}
      </div>

      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={visibleIndices.map((i) => rows[i].id)}
          strategy={verticalListSortingStrategy}
        >
          <EditableList onAdd={addRoute} addLabel="הוסף ציר חדש">
            {visibleIndices.map((i) => {
              const route = routes[i];
              const disconnected =
                componentCount > 1 &&
                route.places.length > 0 &&
                find(route.places[0]) !== mainRoot;
              return (
                <RouteRow
                  key={rows[i].id}
                  id={rows[i].id}
                  index={i}
                  route={route}
                  suggestions={suggestions}
                  highlight={highlight}
                  disconnected={disconnected}
                  pinned={rows[i].pinned}
                  filteredOut={Boolean(filtering) && !matched.has(i)}
                  compromisedPlaces={compromisedPlaces}
                  onChangeRoute={(nextRoute) => patchRoute(i, nextRoute)}
                  onChangePriority={(priority) => patchRoute(i, { priority })}
                  onRemoveRoute={() => removeRoute(i)}
                  onDuplicateRoute={() => duplicateRoute(i)}
                  onTogglePin={() => togglePin(i)}
                  onRenameStop={requestRename}
                />
              );
            })}
          </EditableList>
        </SortableContext>
      </DndContext>

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

/**
 * A priority option: a dot shaded by how far the priority is from the best, then
 * the label. The ramp is what a bare letter can't convey — that these four values
 * are ordered, and that picking a later one costs the route something.
 */
function renderPriorityOption(option) {
  return (
    <>
      <span
        className="priority-dot"
        style={{ "--priority-step": option.value }}
        aria-hidden="true"
      />
      {option.label}
    </>
  );
}

function RouteRow({
  id,
  index,
  route,
  suggestions,
  highlight,
  disconnected,
  pinned,
  filteredOut,
  compromisedPlaces,
  onChangeRoute,
  onChangePriority,
  onRemoveRoute,
  onDuplicateRoute,
  onTogglePin,
  onRenameStop,
}) {
  const { places, priority } = route;
  const origins = leafCount(route); // number of converging origin heads (1 = plain)
  const branched = origins > 1;
  // A plain route needs both endpoints; a branched one is validated per-head.
  const tooShort = !branched && places.length < 2;
  const destination = places[places.length - 1];
  const hasCompromised = routeStops(route).some((p) => compromisedPlaces?.has(p));

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id });

  // Translate on Y only — the list is a single column, and letting a card drift
  // sideways would just detach it from the drop targets it's aiming at.
  const style = {
    transform: transform ? `translate3d(0, ${transform.y}px, 0)` : undefined,
    transition,
  };

  const extraClassName = [
    "route-row--sortable",
    disconnected && "route-row--disconnected",
    hasCompromised && "route-row--compromised",
    pinned && "route-row--pinned",
    isDowngraded(priority) && "route-row--downgraded",
    isDragging && "route-row--dragging",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <EditableGroupRow
      rootRef={setNodeRef}
      style={style}
      warn={tooShort}
      extraClassName={extraClassName}
      badge={
        (branched || places.length >= 2) && (
          <>
            <Pill size="sm" className="route-badge">
              {branched ? `יעד: ${destination}` : `${places[0]} - ${destination}`}
            </Pill>
            {branched && (
              <Pill
                size="sm"
                className="route-branch-count"
                title="מספר המקורות המתכנסים אל היעד"
              >
                <IconBranch size={12} /> {`${origins} מקורות`}
              </Pill>
            )}
          </>
        )
      }
      warning={
        <>
          {tooShort && (
            <span className="route-warn">דרושות לפחות שתי תחנות</span>
          )}
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
          {filteredOut && (
            <span className="route-warn route-warn--muted">
              <IconPin size={13} /> נעוץ — אינו תואם לסינון
            </span>
          )}
        </>
      }
      actions={
        <>
          <Select
            size="md"
            className={
              "route-priority" +
              (isDowngraded(priority) ? " route-priority--downgraded" : "")
            }
            value={priority}
            onChange={onChangePriority}
            options={PRIORITY_OPTIONS}
            renderOption={renderPriorityOption}
            aria-label={`עדיפות ציר ${index + 1}`}
            title="עדיפות הציר — א׳ היא הטובה ביותר. ציר בעדיפות נמוכה ישמש רק אם אין דרך אחרת."
          />
          <IconButton
            className={"route-pin" + (pinned ? " route-pin--on" : "")}
            ariaLabel={
              pinned ? `בטל נעיצת ציר ${index + 1}` : `נעץ ציר ${index + 1}`
            }
            ariaPressed={pinned}
            title={pinned ? "בטל נעיצה" : "נעץ — הציר יישאר גלוי גם בסינון"}
            onClick={onTogglePin}
          >
            <IconPin size={16} />
          </IconButton>
          <IconButton
            ariaLabel={`שכפל ציר ${index + 1}`}
            title="שכפל ציר"
            onClick={onDuplicateRoute}
          >
            <IconDuplicate size={16} />
          </IconButton>
        </>
      }
      onRemove={onRemoveRoute}
      removeLabel={`מחק ציר ${index + 1}`}
      {...attributes}
      // The card is a drag surface, not a control: keep dnd-kit's aria wiring but
      // drop the role/tab-stop it assumes, since the card wraps real buttons and
      // inputs that a role="button" ancestor would bury.
      role={undefined}
      tabIndex={undefined}
      {...listeners}
    >
      <BranchedChain
        route={route}
        onChange={onChangeRoute}
        suggestions={suggestions}
        highlight={highlight}
        onRenameStop={onRenameStop}
        compromisedPlaces={compromisedPlaces}
      />
    </EditableGroupRow>
  );
}
