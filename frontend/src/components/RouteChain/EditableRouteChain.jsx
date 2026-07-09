import { Fragment, useEffect, useRef, useState } from "react";
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
import Autocomplete from "../Autocomplete.jsx";
import { IconChevron, IconPlus, IconTrash } from "../icons.jsx";
import "./RouteChain.css";

let uid = 0;
const toItem = (value) => ({ id: `stop-${uid++}`, value });
const sameValues = (a, b) =>
  a.length === b.length && a.every((v, i) => v === b[i]);

/**
 * Editable variant of <RouteChain>. Renders the exact same resting UI (pills +
 * chevrons + start/end accents), but the stops can be:
 *   - reordered by dragging (dnd-kit, rectSortingStrategy for the wrapping row),
 *   - edited by clicking (inline Autocomplete seeded with the value),
 *   - inserted by clicking any chevron/end gap (it morphs into a "+").
 * Deleting a stop = commit an empty value, or the trash button in the editor.
 *
 * props:
 *   stops        array of place names (controlled)
 *   onChange     (nextStops) => void  — full next array on every mutation
 *   suggestions  known place names for the edit dropdown
 *   highlight    optional lowercased query for search highlighting
 */
export default function EditableRouteChain({
  stops,
  onChange,
  suggestions,
  highlight,
}) {
  // Internal id-keyed model so dnd-kit and the inline editor stay stable across
  // reorders (stop values can duplicate, so they can't be used as keys).
  const [items, setItems] = useState(() => stops.map(toItem));
  const [editingId, setEditingId] = useState(null);
  const [dragging, setDragging] = useState(false);

  // Reconcile external changes (e.g. the server's normalized copy) without
  // clobbering ids/edit state when the new value is just the echo of our own
  // edit or an in-progress (uncommitted) inserted stop.
  useEffect(() => {
    setItems((prev) => {
      const committed = prev.filter((it) => it.value !== "").map((it) => it.value);
      return sameValues(committed, stops) ? prev : stops.map(toItem);
    });
  }, [stops]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );

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
  }

  function commitEdit(id, value) {
    const text = value.trim();
    const next = text
      ? items.map((it) => (it.id === id ? { ...it, value: text } : it))
      : items.filter((it) => it.id !== id);
    setItems(next);
    setEditingId(null);
    emit(next);
  }

  function cancelEdit(id) {
    const it = items.find((x) => x.id === id);
    // A freshly inserted (still empty) stop is discarded on cancel.
    if (it && it.value === "") setItems(items.filter((x) => x.id !== id));
    setEditingId(null);
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
      <SortableContext items={items.map((it) => it.id)} strategy={rectSortingStrategy}>
        <ol className={"chain" + (dragging ? " chain--dragging" : "")}>
          {items.length === 0 ? (
            <li className="chain-item">
              <button
                type="button"
                className="chain-empty-add"
                onClick={() => openInsert(0)}
              >
                <IconPlus size={15} /> הוסף תחנה
              </button>
            </li>
          ) : (
            <>
              <InsertSlot variant="lead" onClick={() => openInsert(0)} />
              {items.map((it, i) => (
                <Fragment key={it.id}>
                  <li className="chain-item">
                    {editingId === it.id ? (
                      <StopEditor
                        initial={it.value}
                        suggestions={suggestions}
                        onCommit={(v) => commitEdit(it.id, v)}
                        onCancel={() => cancelEdit(it.id)}
                      />
                    ) : (
                      <SortableStop
                        item={it}
                        index={i}
                        count={items.length}
                        highlight={highlight}
                        onEdit={() => setEditingId(it.id)}
                      />
                    )}
                    <InsertSlot
                      variant={i < items.length - 1 ? "gap" : "trail"}
                      onClick={() => openInsert(i + 1)}
                    />
                  </li>
                </Fragment>
              ))}
            </>
          )}
        </ol>
      </SortableContext>
    </DndContext>
  );
}

function SortableStop({ item, index, count, highlight, onEdit }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: item.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const matched = highlight && item.value.toLowerCase().includes(highlight);

  return (
    <span
      ref={setNodeRef}
      style={style}
      className={
        "stop stop--editable" +
        (index === 0 ? " stop--start" : "") +
        (index === count - 1 ? " stop--end" : "") +
        (matched ? " stop--match" : "") +
        (isDragging ? " stop--dragging" : "")
      }
      {...attributes}
      {...listeners}
      onClick={onEdit}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onEdit();
        }
      }}
    >
      {item.value}
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

  function finish(value) {
    if (doneRef.current) return;
    doneRef.current = true;
    onCommit(value);
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
        // dropdown option or the trash button).
        if (!e.currentTarget.contains(e.relatedTarget)) finish(draft);
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
        onSelect={finish}
        onSubmit={finish}
        placeholder="שם תחנה…"
      />
      <button
        type="button"
        className="stop-edit-delete"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => finish("")}
        aria-label="מחק תחנה"
      >
        <IconTrash size={15} />
      </button>
    </span>
  );
}

function InsertSlot({ variant, onClick }) {
  return (
    <button
      type="button"
      className={"insert-slot insert-slot--" + variant}
      onClick={onClick}
      aria-label="הוסף תחנה כאן"
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
    </button>
  );
}
