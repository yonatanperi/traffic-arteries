import { useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
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
import { classifyPlace, formatPlace, groupLabel, parseTypedPlace } from "../../../utils/placeGroups.js";
import PlaceGroupPopover from "./PlaceGroupPopover.jsx";
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
 *   ranges        optional `[{ from, to, tone, label, onRemove }]` — inclusive stop
 *                 index ranges to paint as a band across the pills *and* the
 *                 connectors between them, each with a tag at its start. Deliberately
 *                 anonymous: the route editor's priority marks are what fill it, but
 *                 this component only knows "these stops belong together". `tone` is
 *                 a 0..3 ramp step for the band's colour and `label` is any node, so
 *                 the caller owns the vocabulary. Painted whether or not selection is
 *                 on, since a range is a property of the chain, not of the mode.
 *   selectionMode when set, the chain stops being editable (no reorder, no inline
 *                 edit, no insert) and becomes *selectable*: pressing a stop and
 *                 dragging picks stops out, and so does tapping one and then
 *                 another. Reuses the drag gesture the reorder normally owns, which
 *                 is why the two modes are exclusive rather than layered.
 *   selectionKey  opaque id for this chain, reported back with every picked stop.
 *                 Several chains rendered together share one gesture — a drag that
 *                 starts here may end over another — so a stop is only identified by
 *                 *which* chain plus its index.
 *   onSelectStop  (phase, { key, index } | null, at) => void — "start" on press,
 *                 "move" as the pointer crosses stops, "end" on release, with
 *                 whatever stop is under the pointer (possibly another chain's, or
 *                 null on an "end" released over nothing). The caller decides
 *                 what a pair of stops means and what is a legal range: this
 *                 component reports picks and paints what it's told, nothing more.
 *                 `at` is `{ top, right }` in viewport coordinates, taken from the
 *                 stop the gesture ended on, so a caller can pin a menu to it —
 *                 viewport rather than local because the branched map renders the
 *                 chain inside a scaled, panned canvas.
 *   selected      `{ from, to }` | null — this chain's stops currently picked out,
 *                 as the caller computes them.
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
  ranges = null,
  selectionMode = false,
  selectionKey = null,
  selected = null,
  onSelectStop,
}) {
  // Internal id-keyed model so dnd-kit and the inline editor stay stable across
  // reorders (stop values can duplicate, so they can't be used as keys).
  const [items, setItems] = useState(() => stops.map(toItem));
  const [editingId, setEditingId] = useState(null);
  const [dragging, setDragging] = useState(false);
  // Id of a freshly-inserted (not-yet-committed) stop, so we can tell an "add"
  // apart from an "edit" and keep the add chain going on Enter.
  const [addingId, setAddingId] = useState(null);
  // Stops committed with text that matched neither a known suggestion nor a
  // recognized group prefix, queued for the "which group?" popover (one at a
  // time, so a multi-part paste asks once per part). `previousValue` is what
  // to restore on cancel: the prior text for a rename, `null` for a fresh
  // stop (cancelling removes it, same as an abandoned empty add).
  const [askQueue, setAskQueue] = useState([]);
  const [askAnchor, setAskAnchor] = useState(null);
  // Set when a "keep adding" commit also queued a group-ask: the id to open a
  // fresh empty stop after, once every ask from that commit has been answered.
  const pendingContinueRef = useRef(null);
  const suggestionsSet = useMemo(() => new Set(suggestions), [suggestions]);
  // Each suggestion's group is derived from its own prefix, purely for a
  // searchable `keywords` term (e.g. typing "צומת" surfaces every junction).
  const stopOptions = useMemo(
    () =>
      suggestions.map((name) => ({
        value: name,
        label: name,
        keywords: [groupLabel(classifyPlace(name))],
      })),
    [suggestions],
  );
  const currentAsk = askQueue[0] ?? null;

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
  // Selection mode owns the drag gesture, so reorder must give it up entirely.
  const sensors = sortable && !selectionMode ? pointerSensors : NO_SENSORS;

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

  // Computed after commit (not during render), so a stop added this same tick
  // already has a pill in the DOM for `chainItemRefs` to measure. Recomputed
  // (not dismissed) on scroll/resize — the popover answers a question with a
  // destructive "no" (it reverts/removes the stop), so it must never vanish
  // from a merely-incidental scroll the way a plain menu safely could.
  useEffect(() => {
    if (!currentAsk) {
      setAskAnchor(null);
      return;
    }
    function place() {
      const rect = chainItemRefs.current.get(currentAsk.itemId)?.getBoundingClientRect();
      setAskAnchor(
        rect
          ? { top: rect.bottom + 6, right: window.innerWidth - rect.right }
          : { top: 80, right: 80 },
      );
    }
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [currentAsk?.itemId]);

  // Resume "continue adding" (see commitEdit) once every ask it deferred has
  // been answered, one way or another.
  useEffect(() => {
    if (askQueue.length > 0 || !pendingContinueRef.current) return;
    const afterId = pendingContinueRef.current;
    pendingContinueRef.current = null;
    const fresh = toItem("");
    let inserted = false;
    setItems((prev) => {
      const idx = prev.findIndex((it) => it.id === afterId);
      if (idx === -1) return prev;
      inserted = true;
      const next = prev.slice();
      next.splice(idx + 1, 0, fresh);
      return next;
    });
    if (inserted) {
      setEditingId(fresh.id);
      setAddingId(fresh.id);
    }
  }, [askQueue]);

  function resolveCurrentAsk(group) {
    const { itemId, rawText, renameFrom } = currentAsk;
    const resolved = formatPlace(rawText, group);
    setItems((prev) => {
      const next = prev.map((it) => (it.id === itemId ? { ...it, value: resolved } : it));
      emit(next);
      return next;
    });
    if (renameFrom) onRenameStop?.(renameFrom, resolved);
    setAskQueue((q) => q.slice(1));
  }

  function cancelCurrentAsk() {
    const { itemId, previousValue } = currentAsk;
    setItems((prev) => {
      const next =
        previousValue === null
          ? prev.filter((it) => it.id !== itemId)
          : prev.map((it) => (it.id === itemId ? { ...it, value: previousValue } : it));
      emit(next);
      return next;
    });
    setAskQueue((q) => q.slice(1));
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
    // no sense once the edit fans out into several stops. Deferred (not fired
    // here) when the new text itself needs the group-ask popover below — it
    // must propagate the *resolved* (prefixed) text, not the raw typed one,
    // or other routes would rename to a different string than this stop ends
    // up showing.
    const isRename = parts.length === 1 && !wasAdding && prev && prev.value && prev.value !== parts[0];
    const renameNeedsAsk =
      isRename && !suggestionsSet.has(parts[0]) && !parseTypedPlace(parts[0]);
    if (isRename && !renameNeedsAsk) {
      onRenameStop?.(prev.value, parts[0]);
    }

    // A part that matches neither a known suggestion nor a recognized group
    // prefix is committed as typed regardless (above) — never left stuck
    // mid-edit — but queued for the "which group?" popover, which will
    // reconstruct its text with the chosen group's prefix once answered.
    const toAsk = replacement.filter(
      (it) => it.value && !suggestionsSet.has(it.value) && !parseTypedPlace(it.value),
    );
    if (toAsk.length) {
      setAskQueue((q) => [
        ...q,
        ...toAsk.map((it) => ({
          itemId: it.id,
          rawText: it.value,
          previousValue: it.id === prev?.id && !wasAdding ? prev.value : null,
          renameFrom: renameNeedsAsk && it.id === prev?.id ? prev.value : null,
        })),
      ]);
    }

    // Continuous add: after committing a freshly-added stop (or a pasted run
    // of several) via Enter/select, open a new empty stop right after the
    // last one so the user can keep adding. Deferred until any group-ask this
    // very commit raised has been answered — opening a fresh editor at the same
    // time as the popover meant the two competed for attention, and the popover
    // could end up anchored to a pill that had already scrolled away from it.
    if (replacement.length && wasAdding && keepAdding) {
      const lastId = replacement[replacement.length - 1].id;
      if (toAsk.length) {
        pendingContinueRef.current = lastId;
        setEditingId(null);
      } else {
        const idx = next.findIndex((it) => it.id === lastId);
        const fresh = toItem("");
        const withNew = next.slice();
        withNew.splice(idx + 1, 0, fresh);
        setItems(withNew);
        setEditingId(fresh.id);
        setAddingId(fresh.id);
      }
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

  // --- stop picking ------------------------------------------------------
  //
  // The gesture lives here; what a pair of picked stops *means* does not. Several
  // chains may be rendered as one tree, and a drag that starts in one can end in
  // another — so every pick is reported as (chain key, stop index) and the caller
  // resolves it. Whether the pointer is dragging is a ref, not state: it changes on
  // every pointermove and nothing in the render depends on it.
  const draggingRef = useRef(false);

  useEffect(() => {
    if (!selectionMode) draggingRef.current = false;
  }, [selectionMode]);

  // The whole `.chain-item` carries the index — pill *and* the connector after it —
  // so sweeping across a chain never falls into a dead gap between pills. Read off
  // the element under the pointer, which may belong to a *different* chain than the
  // one that captured the gesture; that's the point.
  const pointAt = (target) => {
    const stop = target?.closest?.("[data-stop-index]");
    const chain = stop?.closest?.("[data-selection-key]");
    if (!stop || !chain) return null;
    return { key: chain.dataset.selectionKey, index: Number(stop.dataset.stopIndex) };
  };

  // Pin whatever the caller opens under the stop the gesture ended on — the one the
  // hand is already over. RTL, so the menu's start edge is the right one.
  const anchorRect = (point, event) => {
    const el = document.querySelector(
      `[data-selection-key="${point.key}"] [data-stop-index="${point.index}"]`,
    );
    const rect = el?.getBoundingClientRect();
    return rect
      ? { top: rect.bottom + 6, right: window.innerWidth - rect.right }
      : { top: event.clientY + 6, right: window.innerWidth - event.clientX };
  };

  function startPick(e) {
    if (!selectionMode || e.button !== 0) return;
    const point = pointAt(e.target);
    if (!point) return;
    draggingRef.current = true;
    // Capture on the list, not the pill: the pointer leaves the pill immediately,
    // and elementFromPoint keeps reporting what is under it regardless.
    e.currentTarget.setPointerCapture?.(e.pointerId);
    onSelectStop?.("start", point, anchorRect(point, e));
  }

  function movePick(e) {
    if (!draggingRef.current) return;
    const point = pointAt(document.elementFromPoint(e.clientX, e.clientY));
    if (point) onSelectStop?.("move", point, anchorRect(point, e));
  }

  function endPick(e) {
    if (!draggingRef.current) return;
    draggingRef.current = false;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    // Always reported, even when released over nothing (the empty canvas between
    // segments): the caller is holding the gesture's start and has to be told it
    // ended, or the next press would extend a range from a stop long since let go.
    const point = pointAt(document.elementFromPoint(e.clientX, e.clientY));
    onSelectStop?.("end", point, point ? anchorRect(point, e) : null);
  }

  // Ranges by stop index. Overlap is possible — a mark drawn from a head can reach
  // the shared tail while the tail carries one of its own — so the pill shows the
  // *worst* range covering it, the one that costs a route the most.
  const rangeAt = (index) =>
    ranges?.reduce(
      (worst, range) =>
        index >= range.from &&
        index <= range.to &&
        (!worst || range.tone > worst.tone)
          ? range
          : worst,
      null,
    ) ?? null;
  // A tag belongs to the range's *start*, which for a range spilling in from another
  // chain isn't here at all — the caller labels only the piece that owns it.
  const tagsAt = (index) =>
    ranges?.filter((range) => range.label && range.from === index) ?? [];
  const inSelection = (index) =>
    Boolean(selected) && index >= selected.from && index <= selected.to;

  // The leading "+" (add a stop / — on a junction tail — a sibling head at the
  // junction). Lives at the very start of the chain (row 0 when wrapped).
  const lead = (
    <InsertSlot
      variant="lead"
      disabled={selectionMode}
      onAddStop={() => openInsert(0)}
      onAddBranch={onAddBranch && isJunction ? () => onAddBranch(0) : undefined}
      branchLabel="הוסף ראש"
    />
  );

  // One stop: its pill (or inline editor) plus the "+"/chevron gap after it.
  const renderStop = (it, i) => {
    const range = rangeAt(i);
    // The connector after stop i is inside a range only when stop i + 1 is too — it
    // *is* that hop, so the band has to stop at the range's last pill. A range
    // reaching past this chain's last stop carries on into the next segment, and its
    // trailing connector is the junction hop, so that one stays painted too.
    const linked = range && (i < range.to || range.continues);
    const picked = inSelection(i);
    const pickedLink = picked && (inSelection(i + 1) || selected?.continues);
    const stopProps = {
      item: it,
      index: i,
      count: items.length,
      highlight,
      showStart,
      showEnd,
      compromised: compromisedPlaces?.has(it.value),
      tone: range?.tone,
      marked: Boolean(range),
      selected: picked,
    };
    return (
      <li
        className="chain-item"
        key={it.id}
        data-stop-index={selectionMode ? i : undefined}
        ref={(el) => {
          if (el) chainItemRefs.current.set(it.id, el);
          else chainItemRefs.current.delete(it.id);
        }}
      >
        {tagsAt(i).map((tagged, k) => (
          <RangeTag key={k} range={tagged} />
        ))}
        {editingId === it.id && !selectionMode ? (
          <StopEditor
            initial={it.value}
            suggestions={stopOptions}
            onCommit={(v, keepAdding) => commitEdit(it.id, v, keepAdding)}
            onCancel={() => cancelEdit(it.id)}
          />
        ) : selectionMode ? (
          <SelectableStop {...stopProps} />
        ) : (
          <SortableStop
            {...stopProps}
            dragging={dragging}
            // A hover preview shows the flipped order but isn't itself draggable —
            // it's not a real state to reorder from, just a glimpse of the reverse.
            sortable={sortable && !previewReversed}
            onEdit={() => setEditingId(it.id)}
            onRemove={() => removeStop(it.id)}
          />
        )}
        <InsertSlot
          variant={i < items.length - 1 ? "gap" : "trail"}
          disabled={selectionMode}
          tone={linked ? range.tone : undefined}
          marked={Boolean(linked)}
          selected={pickedLink}
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
  };

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
    <>
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
              (dragging ? " chain--dragging" : "") +
              (selectionMode ? " chain--selecting" : "")
            }
            data-selection-key={selectionMode ? selectionKey : undefined}
            onPointerDown={selectionMode ? startPick : undefined}
            onPointerMove={selectionMode ? movePick : undefined}
            onPointerUp={selectionMode ? endPick : undefined}
            onPointerCancel={selectionMode ? endPick : undefined}
          >
            {body}
          </ol>
        </SortableContext>
      </DndContext>
      {currentAsk && askAnchor && (
        <PlaceGroupPopover
          at={askAnchor}
          baseName={currentAsk.rawText}
          onPick={resolveCurrentAsk}
          onClose={cancelCurrentAsk}
        />
      )}
    </>
  );
}

/** The classes every pill shares, whichever mode renders it. */
function stopClassName({ index, count, showStart, showEnd, matched, compromised, marked, selected }) {
  return (
    "stop stop--editable" +
    (showStart && index === 0 ? " stop--start" : "") +
    (showEnd && index === count - 1 ? " stop--end" : "") +
    (matched ? " stop--match" : "") +
    (compromised ? " stop--compromised" : "") +
    (marked ? " stop--marked" : "") +
    (selected ? " stop--selected" : "")
  );
}

/**
 * A pill in selection mode: no drag, no inline edit, no remove — the press
 * belongs to the range sweep on the list, so the pill deliberately handles
 * nothing itself and only reports how it should look.
 */
function SelectableStop({
  item,
  index,
  count,
  highlight,
  showStart = true,
  showEnd = true,
  compromised,
  tone,
  marked,
  selected,
}) {
  return (
    <span
      className={
        stopClassName({
          index,
          count,
          showStart,
          showEnd,
          matched: isMatch(item.value, highlight),
          compromised,
          marked,
          selected,
        }) + " stop--static"
      }
      style={marked ? { "--priority-step": tone } : undefined}
      aria-selected={selected || undefined}
    >
      {item.value}
    </span>
  );
}

/** The tag at a range's start: whatever the caller calls it, plus a way out. */
function RangeTag({ range }) {
  return (
    <span className="chain-range-tag" style={{ "--priority-step": range.tone }}>
      {range.label}
      {range.onRemove && (
        <IconButton
          size="xs"
          className="chain-range-remove"
          ariaLabel="הסר טווח"
          title="הסר טווח"
          // Never let this start a sweep or a card drag on the way through.
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            range.onRemove();
          }}
        >
          <IconClose size={11} />
        </IconButton>
      )}
    </span>
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
  tone,
  marked,
  selected,
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
    ...(marked ? { "--priority-step": tone } : null),
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
        stopClassName({
          index,
          count,
          showStart,
          showEnd,
          matched,
          compromised,
          marked,
          selected,
        }) +
        (hovered ? " stop--hovered" : "") +
        (isDragging ? " stop--dragging" : "") +
        (sortable ? "" : " stop--static")
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
function InsertSlot({
  variant,
  onAddStop,
  onAddBranch,
  branchLabel = "הוסף הסתעפות",
  disabled = false,
  tone,
  marked = false,
  selected = false,
}) {
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
      // In selection mode the slot keeps its chevron — it is the hop between two
      // stops, and a range has to paint across it — but stops being a control.
      disabled={disabled}
      className={
        "insert-slot insert-slot--" +
        variant +
        (menu ? " insert-slot--open" : "") +
        (marked ? " insert-slot--marked" : "") +
        (selected ? " insert-slot--selected" : "")
      }
      style={marked ? { "--priority-step": tone } : undefined}
      onClick={disabled ? undefined : handleClick}
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
