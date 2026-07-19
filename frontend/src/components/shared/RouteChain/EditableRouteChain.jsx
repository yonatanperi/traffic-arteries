import { Fragment, useEffect, useRef, useState } from "react";
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
// read-only-for-reorder (stops still edit/insert/remove, just don't drag) inside
// the branched-route map, where a drag pans the canvas instead.
const NO_SENSORS = [];

let uid = 0;
const toItem = (value) => ({ id: `stop-${uid++}`, value });
const sameValues = (a, b) =>
  a.length === b.length && a.every((v, i) => v === b[i]);

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
 *   sortable      whether stops can be drag-reordered (default true). The branched
 *                 tree passes false: on its pan/zoom map a drag pans the canvas, so
 *                 pills stay click-to-edit but aren't draggable.
 *   showStart / showEnd  whether the first / last stop gets the origin / destination
 *                 accent (default true). The branched tree passes these per segment
 *                 so only a *real* tree edge is accented — a leaf's true origin and
 *                 the tail's final destination — not every sub-branch's internal
 *                 junction endpoints.
 *   wrapEvery     optional stop count after which the row breaks to a new line (via
 *                 a full-width flex break item). Null (default) = wrap only to fit
 *                 the container, as before. The branched map passes 6 so a long
 *                 segment stacks in rows of 6 instead of one line to pan across.
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
    const text = value.trim();
    const prev = items.find((it) => it.id === id);
    const wasAdding = id === addingId;

    const next = text
      ? items.map((it) => (it.id === id ? { ...it, value: text } : it))
      : items.filter((it) => it.id !== id);
    setItems(next);
    setAddingId(null);
    emit(next);

    // Renaming an existing stop: let the parent offer to change every instance.
    if (text && !wasAdding && prev && prev.value && prev.value !== text) {
      onRenameStop?.(prev.value, text);
    }

    // Continuous add: after committing a freshly-added stop via Enter/select,
    // open a new empty stop right after it so the user can keep adding.
    if (text && wasAdding && keepAdding) {
      const idx = next.findIndex((it) => it.id === id);
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

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={() => {
        setEditingId(null);
        setDragging(true);
      }}
      onDragEnd={handleDragEnd}
      onDragCancel={() => setDragging(false)}
    >
      <SortableContext
        items={items.map((it) => it.id)}
        strategy={rectSortingStrategy}
      >
        <ol className={"chain" + (dragging ? " chain--dragging" : "")}>
          {items.length === 0 ? (
            <li className="chain-item">
              <Button
                variant="dashed"
                className="chain-empty-add"
                onClick={() => openInsert(0)}
              >
                <IconPlus size={15} /> הוסף תחנה
              </Button>
            </li>
          ) : (
            <>
              <InsertSlot
                variant="lead"
                onAddStop={() => openInsert(0)}
                // Leading "+" adds a sibling head only on a tail that already
                // branches (split index 0 = the existing junction).
                onAddBranch={
                  onAddBranch && isJunction ? () => onAddBranch(0) : undefined
                }
                branchLabel="הוסף ראש"
              />
              {items.map((it, i) => (
                <Fragment key={it.id}>
                  <li className="chain-item">
                    {editingId === it.id ? (
                      <StopEditor
                        initial={it.value}
                        suggestions={suggestions}
                        onCommit={(v, keepAdding) =>
                          commitEdit(it.id, v, keepAdding)
                        }
                        onCancel={() => cancelEdit(it.id)}
                      />
                    ) : (
                      <SortableStop
                        item={it}
                        index={i}
                        count={items.length}
                        highlight={highlight}
                        dragging={dragging}
                        sortable={sortable}
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
                      // Branch = split at this gap: the stops up to and including
                      // this one (index i → splitIndex i+1) become a head, the rest
                      // the shared tail. Every gap between two stops offers it; the
                      // trailing "+" (i === last) has no tail after it, so it doesn't.
                      onAddBranch={
                        onAddBranch && i < items.length - 1
                          ? () => onAddBranch(i + 1)
                          : undefined
                      }
                    />
                  </li>
                  {/* Force a new row every `wrapEvery` stops: a zero-height,
                      full-width flex item pushes the rest of the chain down. */}
                  {wrapEvery &&
                    (i + 1) % wrapEvery === 0 &&
                    i < items.length - 1 && (
                      <li className="chain-break" aria-hidden="true" />
                    )}
                </Fragment>
              ))}
            </>
          )}
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
