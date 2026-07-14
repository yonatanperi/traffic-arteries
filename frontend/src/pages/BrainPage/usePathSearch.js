import { useMemo, useState } from "react";
import { findPaths } from "../../api/client.js";
import { edgeKey } from "../../utils/graphMetrics.js";
import { unknownPlaces, unknownPlacesMessage } from "../../utils/validatePlaces.js";
import { useWaypoints } from "../../hooks/useWaypoints.js";

/**
 * Owns the brain page's "path" mode: submitting an origin/destination search
 * (with optional required waypoints), the resulting alternative paths, and
 * the node/edge sets for whichever alternative is currently highlighted on
 * the canvas.
 */
export function usePathSearch(placeOptions = []) {
  const [pathResult, setPathResult] = useState(null); // { paths } | null
  const [pathLoading, setPathLoading] = useState(false);
  const [pathError, setPathError] = useState("");
  const [activePathIndex, setActivePathIndex] = useState(0);
  const [waypointIds, setWaypointIds] = useState(null); // stops required by the last submitted search
  const [invalidPlaces, setInvalidPlaces] = useState(() => new Set()); // unknown place names from the last submit attempt
  const { vias, addVia, setVia, removeVia } = useWaypoints();

  const placeSet = useMemo(() => new Set(placeOptions), [placeOptions]);

  async function submitPath(start, end) {
    setPathError("");
    setInvalidPlaces(new Set());
    const via = vias.map((v) => v.trim()).filter(Boolean);
    const unknown = unknownPlaces([start, end, ...via], placeSet);
    if (unknown.length > 0) {
      setInvalidPlaces(new Set(unknown));
      setPathError(unknownPlacesMessage(unknown));
      return;
    }
    setPathLoading(true);
    setPathResult(null);
    setWaypointIds(via.length > 0 ? new Set(via) : null);
    try {
      const res = await findPaths(start, end, via);
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
    setWaypointIds(null);
    setInvalidPlaces(new Set());
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
    waypointIds,
    invalidPlaces,
    submitPath,
    clearPath,
    vias,
    addVia,
    setVia,
    removeVia,
  };
}
