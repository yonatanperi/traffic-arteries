import { useMemo, useState } from "react";
import { findPaths } from "../../api/client.js";
import { edgeKey } from "../../utils/graphMetrics.js";

/**
 * Owns the brain page's "path" mode: submitting an origin/destination search,
 * the resulting alternative paths, and the node/edge sets for whichever
 * alternative is currently highlighted on the canvas.
 */
export function usePathSearch() {
  const [pathResult, setPathResult] = useState(null); // { paths } | null
  const [pathLoading, setPathLoading] = useState(false);
  const [pathError, setPathError] = useState("");
  const [activePathIndex, setActivePathIndex] = useState(0);

  async function submitPath(start, end) {
    setPathError("");
    setPathLoading(true);
    setPathResult(null);
    try {
      const res = await findPaths(start, end);
      setPathResult(res);
      setActivePathIndex(0);
    } catch (e) {
      setPathError(e.message);
    } finally {
      setPathLoading(false);
    }
  }

  function clearPath() {
    setPathResult(null);
    setPathError("");
    setActivePathIndex(0);
  }

  // Nodes / edges of the currently highlighted path.
  const { pathNodes, pathEdges } = useMemo(() => {
    const path = pathResult?.paths?.[activePathIndex];
    if (!path) return { pathNodes: null, pathEdges: null };
    const nodes = new Set(path);
    const edges = new Set();
    for (let i = 0; i < path.length - 1; i += 1) {
      edges.add(edgeKey(path[i], path[i + 1]));
    }
    return { pathNodes: nodes, pathEdges: edges };
  }, [pathResult, activePathIndex]);

  return {
    pathResult,
    pathLoading,
    pathError,
    activePathIndex,
    setActivePathIndex,
    pathNodes,
    pathEdges,
    submitPath,
    clearPath,
  };
}
