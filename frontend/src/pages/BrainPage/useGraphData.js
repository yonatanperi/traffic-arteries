import { useEffect, useMemo, useState } from "react";
import { getGraph } from "../../api/client.js";
import { computeMetrics } from "../../utils/graphMetrics.js";

/**
 * Loads the network graph once on mount and derives the metrics + lookups
 * every other brain-page concern (toolbar, canvas, panels) needs from it.
 */
export function useGraphData() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getGraph()
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const hasGraph = !loading && !error && data && data.nodes.length > 0;

  const metrics = useMemo(() => (data ? computeMetrics(data) : null), [data]);

  const placeOptions = useMemo(
    () => (data ? data.nodes.map((n) => n.id) : []),
    [data],
  );

  // Destinations temporarily marked unavailable — still shown, painted red.
  const compromisedIds = useMemo(
    () => new Set(data ? data.nodes.filter((n) => n.compromised).map((n) => n.id) : []),
    [data],
  );

  return { data, loading, error, hasGraph, metrics, placeOptions, compromisedIds };
}
