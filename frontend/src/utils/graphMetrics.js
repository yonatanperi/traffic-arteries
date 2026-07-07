/**
 * Pure, framework-free graph analysis helpers for the brain (network) view.
 *
 * The graph is undirected and unweighted: nodes are places (`{ id }`) and links
 * are connections (`{ source, target }`). Links may arrive either as raw ids or
 * — once react-force-graph has hydrated them — as node objects, so every helper
 * normalises endpoints through {@link linkEnds}.
 */

/** Normalise a link endpoint that may be an id or a hydrated node object. */
function endId(end) {
  return typeof end === "object" && end !== null ? end.id : end;
}

/** `[sourceId, targetId]` for a link, regardless of hydration state. */
export function linkEnds(link) {
  return [endId(link.source), endId(link.target)];
}

/** Stable key for an undirected edge, independent of endpoint order. */
export function edgeKey(a, b) {
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}

/**
 * Adjacency list as `Map<id, Set<id>>`. Every node id is guaranteed a key even
 * if it has no links, so isolated places are not lost.
 */
export function buildAdjacency(data) {
  const adjacency = new Map();
  data.nodes.forEach((n) => adjacency.set(n.id, new Set()));
  data.links.forEach((l) => {
    const [s, t] = linkEnds(l);
    adjacency.get(s)?.add(t);
    adjacency.get(t)?.add(s);
  });
  return adjacency;
}

/** `Map<id, degree>` derived from an adjacency list. */
export function degreeMap(adjacency) {
  const degrees = new Map();
  for (const [id, neighbours] of adjacency) degrees.set(id, neighbours.size);
  return degrees;
}

/**
 * Connected components via iterative BFS.
 * Returns `{ components, componentOf }` where `components` is an array of id
 * arrays and `componentOf` maps each id to its component index.
 */
export function connectedComponents(adjacency) {
  const componentOf = new Map();
  const components = [];

  for (const start of adjacency.keys()) {
    if (componentOf.has(start)) continue;
    const index = components.length;
    const members = [];
    const queue = [start];
    componentOf.set(start, index);
    while (queue.length) {
      const node = queue.shift();
      members.push(node);
      for (const neighbour of adjacency.get(node)) {
        if (!componentOf.has(neighbour)) {
          componentOf.set(neighbour, index);
          queue.push(neighbour);
        }
      }
    }
    components.push(members);
  }

  return { components, componentOf };
}

/**
 * Articulation points ("critical" places whose removal splits the network),
 * found with an iterative Tarjan lowlink DFS across every component. Iterative
 * to stay safe on large or deep graphs where recursion could overflow.
 */
export function articulationPoints(adjacency) {
  const disc = new Map(); // discovery time
  const low = new Map(); // lowlink
  const parent = new Map();
  const articulation = new Set();
  let timer = 0;

  for (const root of adjacency.keys()) {
    if (disc.has(root)) continue;

    let rootChildren = 0;
    // Frame: { node, iterator over neighbours }
    const stack = [{ node: root, it: adjacency.get(root)[Symbol.iterator]() }];
    disc.set(root, timer);
    low.set(root, timer);
    timer += 1;
    parent.set(root, null);

    while (stack.length) {
      const frame = stack[stack.length - 1];
      const { node } = frame;
      const step = frame.it.next();

      if (step.done) {
        // Backtrack: fold this node's lowlink into its parent and test the
        // articulation condition for that parent.
        stack.pop();
        const par = parent.get(node);
        if (par !== null && par !== undefined) {
          low.set(par, Math.min(low.get(par), low.get(node)));
          if (parent.get(par) !== null && low.get(node) >= disc.get(par)) {
            articulation.add(par);
          }
        }
        continue;
      }

      const neighbour = step.value;
      if (!disc.has(neighbour)) {
        parent.set(neighbour, node);
        disc.set(neighbour, timer);
        low.set(neighbour, timer);
        timer += 1;
        if (node === root) rootChildren += 1;
        stack.push({
          node: neighbour,
          it: adjacency.get(neighbour)[Symbol.iterator](),
        });
      } else if (neighbour !== parent.get(node)) {
        low.set(node, Math.min(low.get(node), disc.get(neighbour)));
      }
    }

    // A DFS root is an articulation point iff it has more than one DFS child.
    if (rootChildren > 1) articulation.add(root);
  }

  return articulation;
}

/** Top-`n` highest-degree hubs as `[{ id, degree }]`, busiest first. */
export function topHubs(degrees, n = 5) {
  return [...degrees.entries()]
    .map(([id, degree]) => ({ id, degree }))
    .filter((h) => h.degree > 0)
    .sort((a, b) => b.degree - a.degree || a.id.localeCompare(b.id))
    .slice(0, n);
}

/**
 * Dead-ends: `isolated` places (degree 0) and `leaves` (degree 1). Both are
 * candidates for data-quality issues in the route network.
 */
export function deadEnds(degrees) {
  const isolated = [];
  const leaves = [];
  for (const [id, degree] of degrees) {
    if (degree === 0) isolated.push(id);
    else if (degree === 1) leaves.push(id);
  }
  isolated.sort((a, b) => a.localeCompare(b));
  leaves.sort((a, b) => a.localeCompare(b));
  return { isolated, leaves };
}

/**
 * One-shot bundle of everything the brain page needs, computed from the raw
 * `{ nodes, links }` graph. Callers memoise on `data`.
 */
export function computeMetrics(data) {
  const adjacency = buildAdjacency(data);
  const degrees = degreeMap(adjacency);
  const { components, componentOf } = connectedComponents(adjacency);
  const articulation = articulationPoints(adjacency);
  const ends = deadEnds(degrees);
  const deadEndIds = new Set([...ends.isolated, ...ends.leaves]);
  return {
    adjacency,
    degrees,
    components,
    componentOf,
    articulation,
    hubs: topHubs(degrees, 5),
    deadEnds: ends,
    deadEndIds,
  };
}
