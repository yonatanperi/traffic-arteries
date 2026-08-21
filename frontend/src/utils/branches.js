/**
 * Branched (tree) routes — the pure, immutable tree operations shared by the
 * route editor. Mirrors the backend's `expand_route` in `api/db.py`: this is the
 * single source of truth for how a tree flattens, so the UI's connectivity /
 * suggestions / validity always agree with what the server derives.
 *
 * A route is a *converging tree*: a shared **tail** with **heads** that merge into
 * the start of it. There is no "primary" head — every real corridor is a *leaf*.
 *   - a node is `{ places: [stops toward the tail], branches: [heads] }`
 *   - a node's `branches` are upstream heads whose last stop is adjacent to this
 *     node's first stop (`places[0]`); they nest — a head can split further
 *     upstream into sub-heads.
 *   - priority is stated as *marks*: `{ from, to, priority }` ranges over a node's
 *     **frame** — its own `places` followed by everything downstream of it (see
 *     `nodeFrame`) — inclusive, `from < to`, kept disjoint. An unmarked stretch
 *     rides at the best priority, and a mark only applies to a result that rides the
 *     marked stretch **whole**, so where a rating starts to bite is drawn rather
 *     than guessed. The frame runs past the node so a mark can start in a head and
 *     end in the shared tail; it can only run *downstream*, which stays unambiguous
 *     because heads branch upstream but every node has one way down. Which node
 *     stores a mark is what scopes it: a head's reaches only the corridors below it,
 *     the shared tail's reaches every corridor through it.
 *
 * A node is addressed by a `path` array of branch indices: `[]` is the root
 * (tail), `[0]` its first head, `[0, 1]` that head's second sub-head, and so on.
 */

import { BEST_PRIORITY } from "./priorities.js";

/** A node's heads (`[]` when it has none / the field is absent). */
function branchesOf(node) {
  return node.branches ?? [];
}

const isLeaf = (node) => branchesOf(node).length === 0;

/** A node's own priority marks (`[]` when it states none). */
export function nodeMarks(node) {
  return node?.marks ?? [];
}

/**
 * Flatten a route to its subroutes — the chain from each *leaf* head down the
 * shared tail to the destination (`leaf.places + … + root.places`), each with the
 * marks that apply to it. A flat route (no branches) is its own sole leaf and
 * yields exactly one entry for `route.places`.
 *
 * Marks are gathered on the way down, exactly as the backend does it, and come out
 * as `[startPlace, endPlace, priority]` triples rather than the per-node indices
 * they are stored as: a leaf chain concatenates several nodes, so only names line
 * up across it (and across the filled chain the server derives its graph from).
 * Marking one head therefore rates only the corridors that descend from it, while
 * marking the shared tail rates every corridor that rides it.
 */
export function expandRoute(route) {
  const leaves = [];
  const walk = (node, downstream, downstreamMarks) => {
    // `downstream` is the chain from this node's parent junction to the
    // destination; this node's own stops flow into its front, and its own marks
    // onto the front of the spine's. `full` *is* this node's frame, so it already
    // holds exactly what its mark indices address.
    const full = [...node.places, ...downstream];
    const marks = [
      ...nodeMarks(node)
        .filter((m) => full[m.from] != null && full[m.to] != null)
        .map((m) => [full[m.from], full[m.to], m.priority]),
      ...downstreamMarks,
    ];
    if (isLeaf(node)) leaves.push({ places: full, marks });
    else for (const head of branchesOf(node)) walk(head, full, marks);
  };
  walk(route, [], []);
  return leaves;
}

/**
 * The distinct priorities this route's corridors are rated at, best first — feeds
 * the card's header badge and the toolbar's priority filter.
 *
 * A corridor with no marks at all contributes `BEST_PRIORITY`; one with marks
 * contributes theirs. So an unmarked route reads as `[0]`, a fully-marked one as
 * just its rating, and a tree with one marked head beside a clean one as both —
 * which is what makes filtering by the best priority still mean something.
 */
export function routePriorities(route) {
  const stated = [];
  for (const leaf of expandRoute(route)) {
    if (leaf.marks.length === 0) stated.push(BEST_PRIORITY);
    else stated.push(...leaf.marks.map(([, , priority]) => priority));
  }
  if (!stated.length) stated.push(BEST_PRIORITY);
  return [...new Set(stated)].sort((a, b) => a - b);
}

/** Every stop name in a route (tail + all heads, recursive). */
export function routeStops(route) {
  const stops = [];
  const walk = (node) => {
    stops.push(...node.places);
    for (const head of branchesOf(node)) walk(head);
  };
  walk(route);
  return stops;
}

// --- immutable edits -----------------------------------------------------
//
// Each returns a new route with only the addressed node's ancestor spine rebuilt,
// so React sees fresh objects exactly where something changed.

/** Locate the node at `path` within `route` (`[]` = the route itself). */
export function nodeAt(route, path) {
  return path.reduce((node, i) => branchesOf(node)[i], route);
}

/** A path as a value-comparable key (paths are arrays, so `===` won't do). */
export const pathKey = (path) => path.join(".");

/** The path a key came from. */
export const keyPath = (key) => (key === "" ? [] : key.split(".").map(Number));

/**
 * The nodes downstream of `path`, nearest first: its parent, its grandparent, …,
 * the root. A node's downstream is unique — heads branch upstream and converge —
 * which is what makes a mark reaching past its own node unambiguous.
 */
export function downstreamNodes(route, path) {
  const out = [];
  for (let i = path.length - 1; i >= 0; i--) {
    const p = path.slice(0, i);
    out.push({ path: p, places: nodeAt(route, p).places });
  }
  return out;
}

/**
 * The chain a node's mark indices address: its own stops, then everything
 * downstream. `from` always sits in the node's own places; only `to` may reach past
 * them, into the tail the node flows into.
 */
export function nodeFrame(route, path) {
  return [
    ...nodeAt(route, path).places,
    ...downstreamNodes(route, path).flatMap((d) => d.places),
  ];
}

/**
 * Split a range over a node's frame into the per-node pieces that render it:
 * `[{ path, from, to }]`, the node's own piece first, then one per downstream node
 * the range reaches. This is the one place the frame is taken apart, so a stored
 * mark and a live selection are painted by the same arithmetic.
 */
export function framePieces(route, path, from, to) {
  const own = nodeAt(route, path).places.length;
  const pieces = [{ path, from, to: Math.min(to, own - 1) }];
  let offset = own;
  for (const node of downstreamNodes(route, path)) {
    if (to < offset) break;
    pieces.push({
      path: node.path,
      from: Math.max(from - offset, 0),
      to: Math.min(to - offset, node.places.length - 1),
    });
    offset += node.places.length;
  }
  return pieces;
}

/**
 * Where a stop sits in another node's frame: `{ path, index }` → an index into the
 * frame of `path`, or `null` when it isn't downstream of it at all.
 */
function frameIndex(route, path, point) {
  if (pathKey(path) === pathKey(point.path)) return point.index;
  let offset = nodeAt(route, path).places.length;
  for (const node of downstreamNodes(route, path)) {
    if (pathKey(node.path) === pathKey(point.path)) return offset + point.index;
    offset += node.places.length;
  }
  return null;
}

/**
 * Every mark in the tree, cut into the per-node pieces that render it:
 * `Map<pathKey, [{ from, to, priority, owner, markIndex, head, continues }]>`.
 *
 * A mark reaching past its own node paints on the segments it runs into as well, so
 * one drawn from a head into the shared tail reads as the single stretch it is.
 * `head` flags the piece holding the mark's start — the one place it can be labelled
 * and removed — and `continues` the pieces whose stretch carries on into the next
 * segment, so the junction hop between them stays painted.
 *
 * Two heads' marks can therefore both reach the same tail and overlap there. That is
 * honest — each rates only the corridors below its own head — so they are all
 * reported and the renderer decides what a stop shared by two of them looks like.
 */
export function markPieces(route) {
  const out = new Map();
  const walk = (node, path) => {
    nodeMarks(node).forEach((mark, markIndex) => {
      const pieces = framePieces(route, path, mark.from, mark.to);
      pieces.forEach((piece, i) => {
        const key = pathKey(piece.path);
        if (!out.has(key)) out.set(key, []);
        out.get(key).push({
          from: piece.from,
          to: piece.to,
          priority: mark.priority,
          owner: path,
          markIndex,
          head: i === 0,
          continues: i < pieces.length - 1,
        });
      });
    });
    branchesOf(node).forEach((head, i) => walk(head, [...path, i]));
  };
  walk(route, []);
  return out;
}

/**
 * Turn two picked stops into the mark they describe: `{ path, from, to }`, or
 * `null` when they don't describe one.
 *
 * The pair must lie on a single spine — one stop downstream of the other, or both
 * in the same segment. Two stops on *sibling* heads describe no single stretch of
 * road (nothing rides both), and a stretch is stored on its upstream end, so the
 * node further from the destination is the one that gets the mark. Which end the
 * author swept from is irrelevant; the road is the same either way.
 */
export function resolveRange(route, a, b) {
  const [up, down] = a.path.length >= b.path.length ? [a, b] : [b, a];
  const from = up.index;
  const to = frameIndex(route, up.path, down);
  if (to == null) return null; // not on one spine — sibling heads
  const lo = Math.min(from, to);
  const hi = Math.max(from, to);
  // Same segment sweeps can come out either way round; a cross-segment one can't,
  // since the upstream node's own stops all precede its downstream.
  if (lo === hi) return null; // one stop spans no road to rate
  return { path: up.path, from: lo, to: hi };
}

/** Rebuild `node` by mapping the descendant on `path` through `fn` (recursively). */
function updateAt(node, path, fn) {
  if (path.length === 0) return fn(node);
  const [head, ...rest] = path;
  const branches = branchesOf(node).map((b, i) =>
    i === head ? updateAt(b, rest, fn) : b,
  );
  return withBranches(node, branches);
}

/** A copy of `node` with its branches replaced (dropping the field when empty). */
function withBranches(node, branches) {
  const next = { ...node };
  if (branches.length) next.branches = branches;
  else delete next.branches;
  return next;
}

/** A copy of `node` with its marks replaced (dropping the field when empty), kept
 *  sorted by `from` — the order the editor draws the bars in, and the order the
 *  server stores them in, so a round-trip never reshuffles the list. */
function withMarks(node, marks) {
  const next = { ...node };
  if (marks.length) next.marks = [...marks].sort((a, b) => a.from - b.from);
  else delete next.marks;
  return next;
}

/**
 * Map each index of `prev` onto its index in `next`, or `-1` where the stop is
 * gone — a greedy walk matching by name, which covers what the chain editor
 * actually emits: a stop inserted, a stop removed, a stop renamed in place.
 *
 * An edit that keeps the length (a rename, a drag-reorder) maps to the identity
 * instead: a drawn range is *positional*, so dragging a stop out of it should
 * leave the range where the author put it rather than chase the stop around.
 */
function alignIndices(prev, next) {
  if (prev.length === next.length) return prev.map((_, i) => i);
  const map = new Array(prev.length).fill(-1);
  let cursor = 0;
  for (let i = 0; i < prev.length; i++) {
    let k = cursor;
    while (k < next.length && next[k] !== prev[i]) k++;
    if (k < next.length) {
      map[i] = k;
      cursor = k + 1;
    }
  }
  return map;
}

/**
 * `marks` carried from the `prev` stops of one node onto its `next` ones.
 *
 * Only the node's *own* stops changed, so a mark is remapped in two parts: the
 * stretch inside this node follows its stops by name, and anything reaching
 * downstream just shifts by however many stops the node gained or lost — those
 * stops are untouched, and it is only their offset in the frame that moved.
 *
 * A mark survives as long as two of the stops it spanned do, so removing a stop
 * inside it shortens it and removing an endpoint pulls it in to the nearest stop it
 * still covers. One left spanning no edge is dropped: there is nothing to ride, and
 * the server would reject it. So is one whose start is gone — a mark has to begin in
 * the node that stores it.
 */
function remapMarks(marks, prev, next) {
  if (!marks.length) return [];
  const map = alignIndices(prev, next);
  const shift = next.length - prev.length;
  const out = [];
  for (const mark of marks) {
    const inside = [];
    for (let i = mark.from; i <= Math.min(mark.to, prev.length - 1); i++) {
      if (map[i] >= 0) inside.push(map[i]);
    }
    if (!inside.length) continue; // its start is gone with the stops it began on
    const from = inside[0];
    const to =
      mark.to >= prev.length ? mark.to + shift : inside[inside.length - 1];
    if (to > from) out.push({ ...mark, from, to });
  }
  return out;
}

/**
 * `marks` of a node *upstream* of the one being edited, whose frame runs through it.
 *
 * Only `to` can be affected — a mark's `from` sits in its own node's places, which
 * are not the ones that changed — and only when it reaches the edited node at all.
 * Past the edited node the stops are untouched and merely sit at a new offset, so
 * they shift; inside it, the mark ends at the last stop it covered that survived, or
 * just short of the node when none did.
 */
function remapReachingMarks(marks, offset, prev, next) {
  if (!marks.length) return [];
  const map = alignIndices(prev, next);
  const shift = next.length - prev.length;
  const out = [];
  for (const mark of marks) {
    if (mark.to < offset) {
      out.push(mark); // stops short of the edited node — nothing moved under it
      continue;
    }
    let to;
    if (mark.to >= offset + prev.length) {
      to = mark.to + shift;
    } else {
      const kept = [];
      for (let i = 0; i <= mark.to - offset; i++) if (map[i] >= 0) kept.push(map[i]);
      to = kept.length ? offset + kept[kept.length - 1] : offset - 1;
    }
    if (to > mark.from) out.push({ ...mark, to });
  }
  return out;
}

/** Apply that to every node upstream of the edited one (its heads, recursively). */
function remapUpstream(node, offset, prev, next) {
  const heads = branchesOf(node);
  if (!heads.length) return node;
  return withBranches(
    node,
    heads.map((head) =>
      remapUpstream(
        withMarks(head, remapReachingMarks(nodeMarks(head), offset + head.places.length, prev, next)),
        offset + head.places.length,
        prev,
        next,
      ),
    ),
  );
}

/**
 * Replace the `places` chain of the node at `path`, carrying every mark drawn over
 * those stops across — the node's own, and any reaching into them from a head
 * upstream, whose frame runs through this node (see `nodeFrame`).
 */
export function patchNodePlaces(route, path, places) {
  return updateAt(route, path, (node) =>
    remapUpstream(
      withMarks({ ...node, places }, remapMarks(nodeMarks(node), node.places, places)),
      0,
      node.places,
      places,
    ),
  );
}

/**
 * Rate the stops `[from, to]` of the node at `path` (inclusive, either order).
 *
 * Any existing mark sharing an *edge* with the new range yields it: the parts
 * outside survive as marks of their own, so re-marking the middle of a stretch
 * splits it in two rather than stacking. Two marks may still meet at a stop —
 * they share no edge there, and forbidding it would silently eat one.
 *
 * `BEST_PRIORITY` states nothing an unmarked stretch doesn't, so it *clears* the
 * range instead of marking it — which is what the picker's first option is for.
 */
export function setMark(route, path, from, to, priority) {
  const lo = Math.min(from, to);
  const hi = Math.max(from, to);
  if (hi <= lo) return route;
  return updateAt(route, path, (node) => {
    const kept = [];
    for (const mark of nodeMarks(node)) {
      if (mark.to <= lo || mark.from >= hi) kept.push(mark);
      else {
        if (mark.from < lo) kept.push({ ...mark, to: lo });
        if (mark.to > hi) kept.push({ ...mark, from: hi });
      }
    }
    if (priority > BEST_PRIORITY) kept.push({ from: lo, to: hi, priority });
    return withMarks(node, kept);
  });
}

/** Drop the mark at `markIndex` within the node at `path`. */
export function removeMark(route, path, markIndex) {
  return updateAt(route, path, (node) =>
    withMarks(
      node,
      nodeMarks(node).filter((_, i) => i !== markIndex),
    ),
  );
}

/**
 * Branch the segment at `path` at `splitIndex` (an index into its `places`): the
 * stops from `splitIndex` on become the shared tail, the stops before it become
 * one head, and a fresh empty head is added beside it — two equal siblings
 * converging at `places[splitIndex]`, no primary. `splitIndex` must be ≥ 1 (there
 * must be an upstream head to split off).
 *
 * If the split point is already this segment's own junction (`splitIndex === 0`,
 * i.e. it already has heads there) the segment is left in place and only the fresh
 * empty head is appended.
 *
 * No mark is disturbed. The split-off head's frame — its stops, then the new tail,
 * then everything that was already downstream — is exactly the frame the node had
 * before, so a mark starting before the split keeps its indices verbatim, junction
 * or no junction. One starting after it moves onto the tail, where the same stops
 * now sit `splitIndex` earlier.
 */
export function branchAt(route, path, splitIndex) {
  return updateAt(route, path, (node) => {
    if (splitIndex <= 0) {
      // Already a junction start — just add another empty converging head.
      return withBranches(node, [...branchesOf(node), { places: [] }]);
    }
    const marks = nodeMarks(node);
    const head = withBranches(
      withMarks(
        { places: node.places.slice(0, splitIndex) },
        marks.filter((mark) => mark.from < splitIndex),
      ),
      branchesOf(node), // the node's existing upstream heads move onto the split-off head
    );
    return withMarks(
      { ...node, places: node.places.slice(splitIndex), branches: [head, { places: [] }] },
      marks
        .filter((mark) => mark.from >= splitIndex)
        .map((mark) => ({ ...mark, from: mark.from - splitIndex, to: mark.to - splitIndex })),
    );
  });
}

/**
 * Remove the head addressed by `path`. If that leaves its parent with a single
 * head, the parent collapses — the lone head's stops fold back onto the front of
 * the parent's tail (and the head's own sub-heads become the parent's), so a
 * junction never lingers with just one way through it.
 *
 * Both segments' marks survive the merge over the stops they were drawn on: the
 * head's keep their indices verbatim (the merged node's frame starts exactly where
 * the head's did), and the parent's shift past the head's stops. Neither stretch may
 * be silently re-rated by the fold — the corridors through them are the same
 * corridors afterwards.
 */
export function removeBranch(route, path) {
  const parentPath = path.slice(0, -1);
  const index = path[path.length - 1];
  return updateAt(route, parentPath, (parent) => {
    const kept = branchesOf(parent).filter((_, i) => i !== index);
    if (kept.length !== 1) return withBranches(parent, kept);
    // Collapse: the sole remaining head merges into the parent's tail.
    const [only] = kept;
    const offset = only.places.length;
    const merged = withMarks({ ...parent, places: [...only.places, ...parent.places] }, [
      ...nodeMarks(only),
      ...nodeMarks(parent).map((mark) => ({
        ...mark,
        from: mark.from + offset,
        to: mark.to + offset,
      })),
    ]);
    return withBranches(merged, branchesOf(only));
  });
}

/** Rename every occurrence of a stop across the whole tree (tail + heads). */
export function renameStop(route, oldValue, newValue) {
  const mapNode = (node) => ({
    ...node,
    places: node.places.map((p) => (p === oldValue ? newValue : p)),
    ...(node.branches ? { branches: node.branches.map(mapNode) } : {}),
  });
  return mapNode(route);
}

/** Reverse the stop order of a non-tree (leaf, unbranched) route — marks flip with
 *  it, so they stay drawn over the same stretch of road. */
export function reverseRoute(route) {
  const last = route.places.length - 1;
  return withMarks(
    { ...route, places: route.places.slice().reverse() },
    nodeMarks(route).map((mark) => ({
      ...mark,
      from: last - mark.to,
      to: last - mark.from,
    })),
  );
}

/** Deep copy of a route (for duplicate — heads, chains and marks included). */
export function cloneRoute(route) {
  const cloneNode = (node) => ({
    ...node,
    places: node.places.slice(),
    ...(node.marks ? { marks: node.marks.map((mark) => ({ ...mark })) } : {}),
    ...(node.branches ? { branches: node.branches.map(cloneNode) } : {}),
  });
  return cloneNode(route);
}

/** Whether every head under `node` (recursively) has at least one stop. */
function branchesValid(node) {
  return branchesOf(node).every(
    (b) => b.places.length >= 1 && branchesValid(b),
  );
}

/**
 * A route is saveable when a branchless route has ≥2 stops (or a branched tail has
 * ≥1), and every head has ≥1 — the same rule the backend enforces. Used by the
 * autosave validity gate so an in-progress empty tail/head is held, not persisted.
 */
export function isRouteValid(route) {
  const min = isLeaf(route) ? 2 : 1;
  return route.places.length >= min && branchesValid(route);
}

/** Number of leaves (distinct origin heads) in a route — its subroute count. */
export function leafCount(route) {
  return expandRoute(route).length;
}
