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
 *   - the root also carries `priority` (one per whole tree; heads carry none).
 *
 * A node is addressed by a `path` array of branch indices: `[]` is the root
 * (tail), `[0]` its first head, `[0, 1]` that head's second sub-head, and so on.
 */

/** A node's heads (`[]` when it has none / the field is absent). */
function branchesOf(node) {
  return node.branches ?? [];
}

const isLeaf = (node) => branchesOf(node).length === 0;

/**
 * Flatten a route to its subroutes — the chain from each *leaf* head down the
 * shared tail to the destination (`leaf.places + … + root.places`). A flat route
 * (no branches) is its own sole leaf and yields exactly `[route.places]`.
 */
export function expandRoute(route) {
  const leaves = [];
  const walk = (node, downstream) => {
    // `downstream` is the chain from this node's parent junction to the
    // destination; this node's own stops flow into its front.
    const full = [...node.places, ...downstream];
    if (isLeaf(node)) leaves.push(full);
    else for (const head of branchesOf(node)) walk(head, full);
  };
  walk(route, []);
  return leaves;
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

/** Replace the `places` chain of the node at `path`. */
export function patchNodePlaces(route, path, places) {
  return updateAt(route, path, (node) => ({ ...node, places }));
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
 */
export function branchAt(route, path, splitIndex) {
  return updateAt(route, path, (node) => {
    if (splitIndex <= 0) {
      // Already a junction start — just add another empty converging head.
      return withBranches(node, [...branchesOf(node), { places: [] }]);
    }
    const head = withBranches(
      { places: node.places.slice(0, splitIndex) },
      branchesOf(node), // the node's existing upstream heads move onto the split-off head
    );
    const tail = {
      ...node,
      places: node.places.slice(splitIndex),
      branches: [head, { places: [] }],
    };
    return tail;
  });
}

/**
 * Remove the head addressed by `path`. If that leaves its parent with a single
 * head, the parent collapses — the lone head's stops fold back onto the front of
 * the parent's tail (and the head's own sub-heads become the parent's), so a
 * junction never lingers with just one way through it.
 */
export function removeBranch(route, path) {
  const parentPath = path.slice(0, -1);
  const index = path[path.length - 1];
  return updateAt(route, parentPath, (parent) => {
    const kept = branchesOf(parent).filter((_, i) => i !== index);
    if (kept.length !== 1) return withBranches(parent, kept);
    // Collapse: the sole remaining head merges into the parent's tail.
    const [only] = kept;
    return withBranches(
      { ...parent, places: [...only.places, ...parent.places] },
      branchesOf(only),
    );
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

/** Deep copy of a route (for duplicate — heads and their chains included). */
export function cloneRoute(route) {
  const cloneNode = (node) => ({
    ...node,
    places: node.places.slice(),
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
