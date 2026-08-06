import { useContext, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  rectSortingStrategy,
  useSortable,
  arrayMove,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ScaleRefContext } from "../../routes/RouteEditor/scaleContext.js";
import Autocomplete from "../../ui/Autocomplete";
import Button from "../../ui/Button";
import IconButton from "../../ui/IconButton";
import {
  IconChevron,
  IconPlus,
  IconTrash,
  IconClose,
  IconBranch,
} from "../../ui/icons";
import "./RouteChain.css";

// A DndContext with no sensors can never start a drag — used to render the chain
// read-only-for-reorder (stops still edit/insert/remove, just don't drag) where a
// drag must mean something else. (The branched map now *does* allow reorder: a
// press on a pill is excluded from the canvas pan, so it drags to reorder there
// too — only empty-canvas drags pan.)
const NO_SENSORS = [];

// Stops per row when wrapping to a cap of `max`: balanced so the last row is as
// full as possible. n stops span ceil(n/max) rows, and spreading n evenly over
// those rows gives ceil(n/rows) each — e.g. 7 over a cap of 6 → 2 rows of 4 and 3,
// not 6 and 1. Rows are (k, k, …, k, p) with p ≤ k.
function rowSize(n, max) {
  if (!max || n <= max) return Math.max(n, 1);
  return Math.ceil(n / Math.ceil(n / max));
}

let uid = 0;
const toItem = (value) => ({ id: `stop-${uid++}`, value });
const sameValues = (a, b) =>
  a.length === b.length && a.every((v, i) => v === b[i]);

// Typing (or pasting) "X, Y" into a stop editor means two stops, not one
// pill literally named "X, Y" — split on commas and drop empties (a
// trailing/doubled comma), regardless of the exact spacing around them.
const splitStops = (text) =>
  text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

// A stop is "highlighted" if its value matches any of the active search terms.
// `highlight` may be a single lowercased string (results usage) or an array of
// lowercased terms (the editor's multi-filter search).
function isMatch(value, highlight) {
  if (!highlight) return false;
  const v = value.toLowerCase();
  const terms = Array.isArray(highlight) ? highlight : [highlight];
  return terms.some((t) => t && v.includes(t));
}

/**
 * Editable variant of <RouteChain>. Renders the exact same resting UI (pills +
 * chevrons + start/end accents), but the stops can be:
 *   - reordered by dragging (dnd-kit, rectSortingStrategy for the wrapping row),
 *   - edited by clicking (inline Autocomplete seeded with the value),
 *   - inserted by clicking any chevron/end gap (it morphs into a "+"),
 *   - removed via a hover "×" on the pill (or by committing an empty value).
 *
 * props:
 *   stops         array of place names (controlled)
 *   onChange      (nextStops) => void  — full next array on every mutation
 *   suggestions   known place names for the edit dropdown
 *   highlight     optional lowercased query / array of queries for highlighting
 *   onRenameStop  (oldValue, newValue) => void — fired when an existing stop is
 *                 renamed, so the parent can offer to propagate the change.
 *   compromisedPlaces  optional Set of destination names currently marked
 *                 unavailable, painted red
 *   onAddBranch   optional (splitIndex) => void. When given, an insert "+" offers
 *                 a choice — add a stop here, or branch: split the chain *at this
 *                 gap* (`splitIndex` = the number of stops before it) so the stops
 *                 up to here become one converging head and a fresh head is added
 *                 beside them, over the shared tail from `splitIndex` on. Every gap
 *                 between two stops offers it (not the trailing "+", which has no
 *                 tail after it). When absent the "+" inserts a stop directly,
 *                 exactly as before (so the component stays reusable elsewhere).
 *   isJunction    whether this chain is a tail that already has converging heads at
 *                 its start; only then does the leading "+" offer "add head" (a new
 *                 sibling head at the junction, split index 0).
 *   sortable      whether stops can be drag-reordered (default true). Enabled on the
 *                 branched tree too: a press on a pill is excluded from the map's
 *                 canvas pan, so it drags to reorder; the drag stays 1:1 with the
 *                 cursor at any zoom via the ScaleRefContext modifier below.
 *   showStart / showEnd  whether the first / last stop gets the origin / destination
 *                 accent (default true). The branched tree passes these per segment
 *                 so only a *real* tree edge is accented — a leaf's true origin and
 *                 the tail's final destination — not every sub-branch's internal
 *                 junction endpoints.
 *   wrapEvery     optional cap on stops per row. When set, the chain is pre-split
 *                 into balanced rows of at most this many stops (see `rowSize`) and
 *                 stacked as a column of `.chain-line`s, rather than wrapping to fit
 *                 its box. Null (default) = the plain single flowing row that wraps
 *                 to fit, as before. The branched map passes 6.
 *   previewReversed  render the stops back-to-front (same ids, so it rides the same
 *                 drag-reorder animation) without emitting a change — a caller (the
 *                 route editor's reverse button) toggles this on hover to preview
 *                 the flip, and a click commits it via `onChange` instead.
 */
export default function EditableRouteChain({
  stops,
  onChange,
  suggestions,
  highlight,
  onRenameStop,
  compromisedPlaces,
  onAddBranch,
  isJunction = false,
  sortable = true,
  showStart = true,
  showEnd = true,
  wrapEvery = null,
  previewReversed = false,
}) {
  // Internal id-keyed model so dnd-kit and the inline editor stay stable across
  // reorders (stop values can duplicate, so they can't be used as keys).
  const [items, setItems] = useState(() => stops.map(toItem));
  const [editingId, setEditingId] = useState(null);
  const [dragging, setDragging] = useState(false);
  // Id of a freshly-inserted (not-yet-committed) stop, so we can tell an "add"
  // apart from an "edit" and keep the add chain going on Enter.
  const [addingId, setAddingId] = useState(null);

  // Reconcile external changes (e.g. the server's normalized copy) without
  // clobbering ids/edit state when the new value is just the echo of our own
  // edit or an in-progress (uncommitted) inserted stop.
  useEffect(() => {
    setItems((prev) => {
      const committed = prev
        .filter((it) => it.value !== "")
        .map((it) => it.value);
      return sameValues(committed, stops) ? prev : stops.map(toItem);
    });
  }, [stops]);

  const pointerSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );
  const sensors = sortable ? pointerSensors : NO_SENSORS;

  // A manual FLIP for the reverse-preview flip specifically: dnd-kit only
  // animates a reorder that happens *during* a live drag it's tracking (see
  // `defaultAnimateLayoutChanges` — it requires `wasDragging`), so a
  // programmatic reorder like this one would otherwise just snap. `.animate()`
  // (Web Animations API) runs outside of React's style reconciliation, so it
  // can't fight the `style` object dnd-kit itself writes on the same elements.
  const chainItemRefs = useRef(new Map());
  const prevRectsRef = useRef(new Map());
  const prevPreviewRef = useRef(previewReversed);
  useLayoutEffect(() => {
    // Document-relative, not viewport-relative: hovering the button can itself
    // scroll it into view, and a raw getBoundingClientRect() delta across that
    // scroll would read as a giant (wrong) jump instead of the real reorder.
    const nextRects = new Map();
    chainItemRefs.current.forEach((el, itemId) => {
      const r = el.getBoundingClientRect();
      nextRects.set(itemId, { left: r.left + window.scrollX, top: r.top + window.scrollY });
    });

    // Only the transition into/out of the preview gets this treatment — a real
    // drag animates itself, and add/remove/edit are meant to be instant.
    if (prevPreviewRef.current !== previewReversed) {
      nextRects.forEach((rect, itemId) => {
        const prev = prevRectsRef.current.get(itemId);
        if (!prev) return;
        const dx = prev.left - rect.left;
        const dy = prev.top - rect.top;
        if (!dx && !dy) return;
        chainItemRefs.current.get(itemId)?.animate(
          [
            { transform: `translate(${dx}px, ${dy}px)` },
            { transform: "translate(0, 0)" },
          ],
          { duration: 200, easing: "ease" },
        );
      });
    }

    prevRectsRef.current = nextRects;
    prevPreviewRef.current = previewReversed;
  });

  // On the branched map the pill lives inside a scaled canvas, so dnd-kit's
  // screen-pixel drag delta paints at `delta * scale` and drifts from the cursor.
  // Divide the live translate by the current zoom to keep the drag 1:1. The ref
  // has a stable identity (default { current: 1 }), so reading it never re-renders
  // and flat routes / results (scale 1) are a no-op.
  const scaleRef = useContext(ScaleRefContext);
  const scaleModifier = ({ transform }) => {
    const s = scaleRef.current || 1;
    return s === 1 ? transform : { ...transform, x: transform.x / s, y: transform.y / s };
  };

  function emit(next) {
    onChange(next.filter((it) => it.value !== "").map((it) => it.value));
  }

  function handleDragEnd({ active, over }) {
    setDragging(false);
    if (!over || active.id === over.id) return;
    const from = items.findIndex((it) => it.id === active.id);
    const to = items.findIndex((it) => it.id === over.id);
    if (from === -1 || to === -1) return;
    const next = arrayMove(items, from, to);
    setItems(next);
    emit(next);
  }

  function openInsert(index) {
    const item = toItem("");
    const next = items.slice();
    next.splice(index, 0, item);
    setItems(next);
    setEditingId(item.id);
    setAddingId(item.id);
  }

  function removeStop(id) {
    const next = items.filter((it) => it.id !== id);
    setItems(next);
    if (editingId === id) setEditingId(null);
    if (addingId === id) setAddingId(null);
    emit(next);
  }

  // `keepAdding` is set when the commit came from Enter / picking a suggestion,
  // so a fresh add can immediately roll into the next one.
  function commitEdit(id, value, keepAdding) {
    const prev = items.find((it) => it.id === id);
    const wasAdding = id === addingId;
    // A comma-separated commit (typed or pasted) fans out into one item per
    // part, in place of the single item being edited; the first part reuses
    // its id so the pill keeps its identity, the rest are fresh items.
    const parts = splitStops(value);
    const replacement = parts.map((v, i) =>
      i === 0 ? { ...prev, value: v } : toItem(v),
    );

    const next = items.flatMap((it) => (it.id === id ? replacement : [it]));
    setItems(next);
    setAddingId(null);
    emit(next);

    // Renaming an existing stop: only a genuine 1:1 rename (no split, no
    // clearing) qualifies — the parent's "propagate everywhere" prompt makes
    // no sense once the edit fans out into several stops.
    if (
      parts.length === 1 &&
      !wasAdding &&
      prev &&
      prev.value &&
      prev.value !== parts[0]
    ) {
      onRenameStop?.(prev.value, parts[0]);
    }

    // Continuous add: after committing a freshly-added stop (or a pasted run
    // of several) via Enter/select, open a new empty stop right after the
    // last one so the user can keep adding.
    if (replacement.length && wasAdding && keepAdding) {
      const lastId = replacement[replacement.length - 1].id;
      const idx = next.findIndex((it) => it.id === lastId);
      const fresh = toItem("");
      const withNew = next.slice();
      withNew.splice(idx + 1, 0, fresh);
      setItems(withNew);
      setEditingId(fresh.id);
      setAddingId(fresh.id);
    } else {
      setEditingId(null);
    }
  }

  function cancelEdit(id) {
    const it = items.find((x) => x.id === id);
    // A freshly inserted (still empty) stop is discarded on cancel.
    if (it && it.value === "") setItems(items.filter((x) => x.id !== id));
    setEditingId(null);
    setAddingId(null);
  }

  // The leading "+" (add a stop / — on a junction tail — a sibling head at the
  // junction). Lives at the very start of the chain (row 0 when wrapped).
  const lead = (
    <InsertSlot
      variant="lead"
      onAddStop={() => openInsert(0)}
      onAddBranch={onAddBranch && isJunction ? () => onAddBranch(0) : undefined}
      branchLabel="הוסף ראש"
    />
  );

  // One stop: its pill (or inline editor) plus the "+"/chevron gap after it.
  const renderStop = (it, i) => (
    <li
      className="chain-item"
      key={it.id}
      ref={(el) => {
        if (el) chainItemRefs.current.set(it.id, el);
        else chainItemRefs.current.delete(it.id);
      }}
    >
      {editingId === it.id ? (
        <StopEditor
          initial={it.value}
          suggestions={suggestions}
          onCommit={(v, keepAdding) => commitEdit(it.id, v, keepAdding)}
          onCancel={() => cancelEdit(it.id)}
        />
      ) : (
        <SortableStop
          item={it}
          index={i}
          count={items.length}
          highlight={highlight}
          dragging={dragging}
          // A hover preview shows the flipped order but isn't itself draggable —
          // it's not a real state to reorder from, just a glimpse of the reverse.
          sortable={sortable && !previewReversed}
          showStart={showStart}
          showEnd={showEnd}
          compromised={compromisedPlaces?.has(it.value)}
          onEdit={() => setEditingId(it.id)}
          onRemove={() => removeStop(it.id)}
        />
      )}
      <InsertSlot
        variant={i < items.length - 1 ? "gap" : "trail"}
        onAddStop={() => openInsert(i + 1)}
        // Branch = split at this gap: the stops up to and including this one
        // (index i → splitIndex i+1) become a head, the rest the shared tail.
        // Every gap between two stops offers it; the trailing "+" (i === last)
        // has no tail after it, so it doesn't.
        onAddBranch={
          onAddBranch && i < items.length - 1
            ? () => onAddBranch(i + 1)
            : undefined
        }
      />
    </li>
  );

  // Purely a display order: reversed for the hover preview, otherwise identical
  // to `items`. Every mutation (drag/add/remove/edit) still reads and writes
  // `items` itself — the preview never touches the real state.
  const displayItems = previewReversed ? [...items].reverse() : items;

  let body;
  if (displayItems.length === 0) {
    body = (
      <li className="chain-item">
        <Button
          variant="dashed"
          className="chain-empty-add"
          onClick={() => openInsert(0)}
        >
          <IconPlus size={15} /> הוסף תחנה
        </Button>
      </li>
    );
  } else if (wrapEvery) {
    // Pre-split into balanced rows (`.chain-line`s) so the chain stacks as a
    // column instead of wrapping to fit its box. Each line is a nowrap flex row,
    // so the container measures to the widest line — keeping the map's fit/zoom
    // and pan bounds honest (a flex-wrap container mis-measures to the full
    // single-line width, since intrinsic sizing ignores in-flow line breaks).
    const per = rowSize(displayItems.length, wrapEvery);
    const lines = [];
    for (let start = 0, r = 0; start < displayItems.length; start += per, r++) {
      lines.push(
        <li className="chain-line" key={`line-${r}`}>
          {r === 0 && lead}
          {displayItems
            .slice(start, start + per)
            .map((it, k) => renderStop(it, start + k))}
        </li>,
      );
    }
    body = lines;
  } else {
    body = (
      <>
        {lead}
        {displayItems.map(renderStop)}
      </>
    );
  }

  return (
    <DndContext
      sensors={sensors}
      modifiers={[scaleModifier]}
      collisionDetection={closestCenter}
      onDragStart={() => {
        setEditingId(null);
        setDragging(true);
      }}
      onDragEnd={handleDragEnd}
      onDragCancel={() => setDragging(false)}
    >
      <SortableContext
        items={displayItems.map((it) => it.id)}
        strategy={rectSortingStrategy}
      >
        <ol
          className={
            "chain" +
            (wrapEvery ? " chain--wrapped" : "") +
            (dragging ? " chain--dragging" : "")
          }
        >
          {body}
        </ol>
      </SortableContext>
    </DndContext>
  );
}

function SortableStop({
  item,
  index,
  count,
  highlight,
  dragging,
  sortable = true,
  showStart = true,
  showEnd = true,
  compromised,
  onEdit,
  onRemove,
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: item.id });

  // When reorder is off (the branched map), the pill is click-to-edit only — no
  // drag handlers, so a press-drag falls through to the canvas pan underneath.
  const dragProps = sortable ? { ...attributes, ...listeners } : {};

  // CSS.Translate (not CSS.Transform): apply only the x/y translation, never the
  // scaleX/scaleY that rectSortingStrategy adds to make items match the dragged
  // pill's size. Those scales are what made every pill visibly change width mid
  // drag; with translate-only the dragged pill still tracks the cursor 1:1 and
  // neighbours just slide to reorder.
  const style = {
    transform: CSS.Translate.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const matched = isMatch(item.value, highlight);

  // The remove button's reveal is driven by this JS-tracked hover state (a
  // class), not raw CSS :hover — hovering a pill right at a flex-wrap
  // boundary grows it (via .stop-remove's width) onto the next line, moving
  // it out from under the cursor. Raw :hover would drop instantly, shrink the
  // pill back, re-wrap it under the cursor, and re-trigger :hover — an
  // infinite flicker loop. A short grace period on mouseleave absorbs that
  // transient, single-frame hover loss instead of reacting to it.
  const [hovered, setHovered] = useState(false);
  const leaveTimer = useRef(null);

  useEffect(() => () => clearTimeout(leaveTimer.current), []);

  function handleMouseEnter() {
    clearTimeout(leaveTimer.current);
    setHovered(true);
  }
  function handleMouseLeave() {
    leaveTimer.current = setTimeout(() => setHovered(false), 100);
  }

  return (
    <span
      ref={setNodeRef}
      style={style}
      className={
        "stop stop--editable" +
        (hovered ? " stop--hovered" : "") +
        (showStart && index === 0 ? " stop--start" : "") +
        (showEnd && index === count - 1 ? " stop--end" : "") +
        (matched ? " stop--match" : "") +
        (isDragging ? " stop--dragging" : "") +
        (sortable ? "" : " stop--static") +
        (compromised ? " stop--compromised" : "")
      }
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      {...dragProps}
      onClick={onEdit}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onEdit();
        }
      }}
    >
      {item.value}
      {/* The remove control is omitted entirely while any drag is in progress.
          It's collapsed to zero width at rest, so dropping it from the DOM
          changes no layout — but it removes the clipped (overflow:hidden) child
          that otherwise smears on every GPU-transformed pill during a drag. */}
      {!dragging && (
        <IconButton
          size="xs"
          className="stop-remove"
          ariaLabel="הסר תחנה"
          // Don't let the pointer down start a drag or a click-to-edit.
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
        >
          <IconClose size={13} />
        </IconButton>
      )}
    </span>
  );
}

function StopEditor({ initial, suggestions, onCommit, onCancel }) {
  const [draft, setDraft] = useState(initial);
  const wrapRef = useRef(null);
  const doneRef = useRef(false);

  useEffect(() => {
    wrapRef.current?.querySelector("input")?.focus();
  }, []);

  function finish(value, keepAdding) {
    if (doneRef.current) return;
    doneRef.current = true;
    onCommit(value, keepAdding);
  }
  function cancel() {
    if (doneRef.current) return;
    doneRef.current = true;
    onCancel();
  }

  return (
    <span
      className="stop-edit"
      ref={wrapRef}
      onBlur={(e) => {
        // Commit only when focus leaves the whole editor (not to its own
        // dropdown option or the trash button). Blur never chains a new add.
        if (!e.currentTarget.contains(e.relatedTarget)) finish(draft, false);
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          cancel();
        }
      }}
    >
      <Autocomplete
        options={suggestions}
        value={draft}
        onChange={setDraft}
        onSelect={(v) => finish(v, true)}
        onSubmit={(v) => finish(v, true)}
        placeholder="שם תחנה…"
      />
      <IconButton
        size="md"
        danger
        className="stop-edit-delete"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => finish("", false)}
        ariaLabel="מחק תחנה"
      >
        <IconTrash size={15} />
      </IconButton>
    </span>
  );
}

/**
 * The "+" between/around stops. Without `onAddBranch` a click inserts a stop
 * (unchanged). With it, a click opens a tiny chooser — add a stop here, or fork a
 * branch that merges into the stop this slot precedes. The slot stays visually
 * "active" (plus revealed) while its menu is open, even after the pointer leaves.
 */
function InsertSlot({ variant, onAddStop, onAddBranch, branchLabel = "הוסף הסתעפות" }) {
  const [menu, setMenu] = useState(null); // { top, right } while open, else null
  const btnRef = useRef(null);

  function openMenu() {
    const rect = btnRef.current.getBoundingClientRect();
    // Anchor the menu's start edge (RTL: right) under the slot, just below it.
    setMenu({ top: rect.bottom + 6, right: window.innerWidth - rect.right });
  }
  const close = () => setMenu(null);

  // While open, close on an outside press, Escape, or any scroll/resize (which
  // would leave the fixed menu stranded from its slot).
  useEffect(() => {
    if (!menu) return;
    function onDocDown(e) {
      if (!btnRef.current?.contains(e.target) && !e.target.closest?.(".insert-menu"))
        close();
    }
    function onKey(e) {
      if (e.key === "Escape") close();
    }
    document.addEventListener("mousedown", onDocDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", onDocDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [menu]);

  // No branch option: the slot is the plain single-action button it always was.
  const handleClick = onAddBranch ? (menu ? close : openMenu) : onAddStop;

  return (
    <button
      ref={btnRef}
      type="button"
      className={
        "insert-slot insert-slot--" + variant + (menu ? " insert-slot--open" : "")
      }
      onClick={handleClick}
      aria-label={onAddBranch ? "הוסף כאן" : "הוסף תחנה כאן"}
      aria-haspopup={onAddBranch ? "menu" : undefined}
      aria-expanded={onAddBranch ? Boolean(menu) : undefined}
    >
      {variant === "gap" && (
        <span className="insert-slot-chevron" aria-hidden="true">
          <IconChevron size={15} />
        </span>
      )}
      {/* End slots collapse to zero width; a hit-zone in the card padding keeps
          the "before first / after last" region hoverable. */}
      {variant !== "gap" && (
        <span className="insert-slot-hit" aria-hidden="true" />
      )}
      <span className="insert-slot-plus" aria-hidden="true">
        <IconPlus size={14} />
      </span>

      {menu &&
        createPortal(
          <div
            className="insert-menu"
            role="menu"
            style={{ top: menu.top, right: menu.right }}
          >
            <button
              type="button"
              className="insert-menu-item"
              role="menuitem"
              onClick={() => {
                close();
                onAddStop();
              }}
            >
              <IconPlus size={15} /> הוסף תחנה
            </button>
            <button
              type="button"
              className="insert-menu-item"
              role="menuitem"
              onClick={() => {
                close();
                onAddBranch();
              }}
            >
              <IconBranch size={15} /> {branchLabel}
            </button>
          </div>,
          document.body,
        )}
    </button>
  );
}
