import { useEffect, useMemo, useState } from "react";
import { getPlaces, findPaths } from "../../api/client.js";
import { classifyPlace } from "../../utils/placeTypes.js";
import { useOriginDestination } from "../../hooks/useOriginDestination.js";
import { useUrlListParam } from "../../hooks/useUrlParam.js";

/**
 * Owns every piece of state behind the home page's search form and results:
 * the known places list, the origin/destination/waypoints, the search
 * request itself, and the interior-stop type filters applied to its result.
 */
export function useRouteSearch() {
  const [places, setPlaces] = useState([]);
  const { start, setStart, end, setEnd, swap } = useOriginDestination();
  const [vias, setVias] = useUrlListParam("via"); // required intermediate stops
  const [result, setResult] = useState(null); // { paths } | null
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hiddenTypes, setHiddenTypes] = useState(() => new Set()); // stop types filtered out of the results

  // Only interior stops are ever filtered (start/end are always kept), so a
  // filter chip is only worth showing if some route actually has one of that
  // type among its interior stops.
  const presentTypes = useMemo(() => {
    const set = new Set();
    if (!result) return set;
    result.paths.forEach((path) => {
      path.forEach((place, i) => {
        if (i === 0 || i === path.length - 1) return;
        const type = classifyPlace(place);
        if (type) set.add(type);
      });
    });
    return set;
  }, [result]);

  useEffect(() => {
    getPlaces()
      .then(setPlaces)
      .catch((e) => setError(e.message));
  }, []);

  async function submit() {
    setError("");
    if (!start.trim() || !end.trim()) {
      setError("יש לבחור נקודת מוצא ונקודת יעד.");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const via = vias.map((v) => v.trim()).filter(Boolean);
      const data = await findPaths(start.trim(), end.trim(), via);
      setResult(data);
    } catch (e2) {
      setError(e2.message);
    } finally {
      setLoading(false);
    }
  }

  function addVia() {
    setVias((v) => [...v, ""]);
  }
  function setVia(index, value) {
    setVias((v) => v.map((x, i) => (i === index ? value : x)));
  }
  function removeVia(index) {
    setVias((v) => v.filter((_, i) => i !== index));
  }

  function toggleType(key) {
    setHiddenTypes((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return {
    places,
    start,
    setStart,
    end,
    setEnd,
    swap,
    vias,
    addVia,
    setVia,
    removeVia,
    result,
    loading,
    error,
    hiddenTypes,
    presentTypes,
    submit,
    toggleType,
  };
}
