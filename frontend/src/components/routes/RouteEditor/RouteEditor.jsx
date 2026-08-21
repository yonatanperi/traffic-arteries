import { useEffect, useMemo, useRef, useState } from "react";
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
import BranchedChain from "./BranchedChain";
import { PriorityDot } from "./PriorityDot";
// The priority filter below is a multi-select, so it borrows ui/Select's look
// (`.sel*`) without being built on the component — which means nothing else pulls
// that stylesheet into the bundle. Import it here, where the classes are used.
import "../../ui/Select/Select.css";
import {
  IconSearch,
  IconAlert,
  IconDuplicate,
  IconPin,
  IconBranch,
  IconSwap,
  IconChevron,
  IconCheck,
  IconFlag,
} from "../../ui/icons";
import {
  expandRoute,
  routeStops,
  routePriorities,
  cloneRoute,
  renameStop,
  leafCount,
  reverseRoute,
} from "../../../utils/branches.js";
import {
  useGetUrlParams,
  useSetUrlParams,
} from "../../../hooks/useUrlParams.js";
import {
  PRIORITY_OPTIONS,
  isDowngraded,
  priorityLabel,
  priorityLetter,
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
    expandRoute(route).forEach(({ places }) => {
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
 *   routes     array of { places: [place names], priority: 0..3 } (0 = best), each
 *              optionally branched — see utils/branches.js. A branched route's
 *              `priority` is the tree default; a head may state its own.
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
  // Priority filter (dropdown, multi-select) — a route matches if any of its
  // ridden priorities (routePriorities: one per head on a tree) is among
  // these, so filtering by a bad priority still surfaces a branched route
  // whose *other* heads are rated fine.
  const selectedPriorities = getParam("priority", { list: true }).map(Number);
  function setQuery(value) {
    setParams({ q: value });
  }
  function togglePriorityFilter(p) {
    setParams({
      priority: selectedPriorities.includes(p)
        ? selectedPriorities.filter((x) => x !== p)
        : [...selectedPriorities, p],
    });
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

  // A whole-route edit (the tree editor) *replaces* the route — never merges.
  // A tree edit can legitimately drop a field: collapsing a junction leaves a
  // route with no `branches` key at all, and merging that onto the old object
  // would resurrect the very heads the edit just removed (while their stops are
  // already folded into the tail). The tree ops carry `priority` through
  // themselves, so nothing needs the old object.
  function replaceRoute(index, nextRoute) {
    const next = routes.slice();
    next[index] = nextRoute;
    onChange(next);
  }

  function addRoute() {
    onChange([...routes, { places: [] }]);
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

  function reverseRouteAt(index) {
    replaceRoute(index, reverseRoute(routes[index]));
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
  const filtering = selected.length > 0 || q || selectedPriorities.length > 0;

  const matchedIndices = routes
    .map((_, i) => i)
    .filter((i) => {
      // All stops in the route — tail *and* every branch head (recursive) — so a
      // filter by a branch's stop (e.g. an origin head) matches a tree route too,
      // not just its shared tail.
      const stops = routeStops(routes[i]);
      // Every selected destination must appear somewhere in the route (any
      // order), and the live-typed text further narrows the list.
      const hasAll = selected.every((s) =>
        stops.some((p) => p.toLowerCase().includes(s.toLowerCase())),
      );
      const hasQuery = !q || stops.some((p) => p.toLowerCase().includes(q));
      // A route matches the priority filter if *any* of its ridden priorities
      // is selected — a branched route with one bad head and one good one
      // should still surface under either filter chip.
      const hasPriority =
        selectedPriorities.length === 0 ||
        routePriorities(routes[i]).some((p) => selectedPriorities.includes(p));
      return hasAll && hasQuery && hasPriority;
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

        <PriorityFilterSelect
          value={selectedPriorities}
          onToggle={togglePriorityFilter}
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
                  onChangeRoute={(nextRoute) => replaceRoute(i, nextRoute)}
                  onRemoveRoute={() => removeRoute(i)}
                  onDuplicateRoute={() => duplicateRoute(i)}
                  onReverseRoute={() => reverseRouteAt(i)}
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
 * The priority filter: a dropdown over PRIORITY_OPTIONS, but multi-select — asking
 * "show me anything rated any of these", so choosing an option toggles it and
 * leaves the list open rather than closing on the first pick. (It is the only
 * priority *list* outside <PriorityMarkPopover>, and a deliberately different
 * question: that one rates one stretch, this one filters the whole editor.)
 *
 * props:
 *   value     array of selected priorities (0..3), empty = no filter
 *   onToggle  (priority) => void
 */
function PriorityFilterSelect({ value, onToggle }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);

  useEffect(() => {
    function onDocClick(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target))
        setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const label =
    value.length === 0
      ? "כל העדיפויות"
      : value
          .slice()
          .sort((a, b) => a - b)
          .map(priorityLetter)
          .join(", ");

  return (
    <div
      className={"sel sel--md priority-filter-sel" + (open ? " sel--open" : "")}
      ref={wrapRef}
    >
      <button
        type="button"
        className={"sel-field" + (open ? " sel-field--open" : "")}
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="sel-value">{label}</span>
        <IconChevron size={13} className="sel-chevron" />
      </button>

      {open && (
        <ul className="sel-list" role="listbox" aria-multiselectable="true">
          {PRIORITY_OPTIONS.map((opt) => {
            const checked = value.includes(opt.value);
            return (
              <li
                key={opt.value}
                role="option"
                aria-selected={checked}
                className={
                  "sel-option" + (checked ? " sel-option--selected" : "")
                }
                // mousedown, not click: keeps focus on the trigger and fires before
                // the outside-click listener above would otherwise close this first.
                onMouseDown={(e) => {
                  e.preventDefault();
                  onToggle(opt.value);
                }}
              >
                <PriorityDot priority={opt.value} />
                {opt.label}
                {checked && (
                  <IconCheck size={14} className="priority-filter-check" />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
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
  onRemoveRoute,
  onDuplicateRoute,
  onReverseRoute,
  onTogglePin,
  onRenameStop,
}) {
  const { places } = route;
  const origins = leafCount(route); // number of converging origin heads (1 = plain)
  // Whether this route is a *tree* — asked of the branches themselves, not of the
  // leaf count: a route with a single head still has a head chip to rate, a tail
  // that may be one stop, and no meaningful "reverse", exactly like a bushier one.
  const branched = (route.branches?.length ?? 0) > 0;
  // The priorities the route's corridors ride at — one per distinct rating its
  // marks state, plus the best for anything left unmarked. The *worst* is what the
  // card warns about (one bad corridor is enough). No card carries a priority
  // control any more — a rating is drawn on the stops — so this badge is where the
  // header says anything about rating at all: shown as soon as there is something
  // to say, i.e. more than one value or a downgrade.
  const ridden = routePriorities(route);
  const worstPriority = ridden[ridden.length - 1];
  const showPrioritySpread = ridden.length > 1 || isDowngraded(worstPriority);
  // Turns every chain in the card into a selectable one, so a stretch of stops can
  // be swept out and rated. Per card: rating one route is a whole task on its own,
  // and a global mode would take reordering away from every other card at once.
  const [priorityMode, setPriorityMode] = useState(false);
  // Hovering the reverse button previews the flipped order (via the chain's own
  // drag-reorder animation) without touching the route — nothing persists until
  // the click. Leaving without clicking just lets the preview relax back.
  const [reversePreview, setReversePreview] = useState(false);
  // A plain route needs both endpoints; a branched one is validated per-head.
  const tooShort = !branched && places.length < 2;
  const destination = places[places.length - 1];
  const hasCompromised = routeStops(route).some((p) =>
    compromisedPlaces?.has(p),
  );

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
    priorityMode && "route-row--priority-mode",
    disconnected && "route-row--disconnected",
    hasCompromised && "route-row--compromised",
    pinned && "route-row--pinned",
    isDowngraded(worstPriority) && "route-row--downgraded",
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
              {branched
                ? `יעד: ${destination}`
                : `${places[0]} - ${destination}`}
            </Pill>
            {origins > 1 && (
              <Pill
                size="sm"
                className="route-branch-count"
                title="מספר המקורות המתכנסים אל היעד"
              >
                <IconBranch size={12} /> {`${origins} מקורות`}
              </Pill>
            )}
            {showPrioritySpread && (
              <Pill
                size="sm"
                className="route-priority-spread"
                title="העדיפויות שסומנו על הציר. כל סימון חל על קטע מסוים, ורק מסלול שנוסע בו במלואו נחשב כמי שרכב עליו."
              >
                {ridden.map((p) => (
                  <PriorityDot key={p} priority={p} />
                ))}
                {ridden.length > 1
                  ? `עדיפויות ${ridden.map(priorityLetter).join(", ")}`
                  : priorityLabel(worstPriority)}
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
          {/* There is no priority *picker* on a card: a rating applies to a stretch
              of stops, so it is stated by sweeping that stretch out. This toggle is
              what turns the card's chains into selectable ones. */}
          <IconButton
            className={
              "route-priority-mode" +
              (priorityMode ? " route-priority-mode--on" : "")
            }
            ariaLabel={
              priorityMode
                ? `סיים סימון עדיפויות בציר ${index + 1}`
                : `סמן עדיפויות בציר ${index + 1}`
            }
            ariaPressed={priorityMode}
            title={
              priorityMode
                ? "סיים סימון — חזרה לעריכת התחנות"
                : "סמן עדיפות — בחר טווח תחנות וקבע לו עדיפות. העדיפות חלה רק על מסלול שנוסע בטווח כולו."
            }
            onClick={() => setPriorityMode((on) => !on)}
          >
            <IconFlag size={16} />
          </IconButton>
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
          {!branched && !priorityMode && (
            <IconButton
              ariaLabel={`הפוך את כיוון ציר ${index + 1}`}
              title="הפוך כיוון"
              onMouseEnter={() => setReversePreview(true)}
              onMouseLeave={() => setReversePreview(false)}
              onClick={() => {
                onReverseRoute();
                setReversePreview(false);
              }}
            >
              <IconSwap size={16} />
            </IconButton>
          )}
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
        priorityMode={priorityMode}
        previewReversed={reversePreview}
      />
    </EditableGroupRow>
  );
}
