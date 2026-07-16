import { useEffect, useMemo, useState } from "react";
import { getPlaces, findPaths } from "../../api/client.js";
import { classifyPlace } from "../../utils/placeTypes.js";
import { unknownPlaces, unknownPlacesMessage } from "../../utils/validatePlaces.js";
import { useOriginDestination } from "../../hooks/useOriginDestination.js";
import { useWaypoints } from "../../hooks/useWaypoints.js";

/**
 * Owns every piece of state behind the home page's search form and results:
 * the known places list, the origin/destination/waypoints, the search
 * request itself, and the interior-stop type filters applied to its result.
 */
export function useRouteSearch() {
  const [places, setPlaces] = useState([]);
  const { start, setStart, end, setEnd, swap } = useOriginDestination();
  const { vias, addVia, setVia, removeVia } = useWaypoints();
  const [result, setResult] = useState(null); // { paths } | null
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [invalidPlaces, setInvalidPlaces] = useState(() => new Set()); // unknown place names from the last submit attempt
  const [hiddenTypes, setHiddenTypes] = useState(() => new Set()); // stop types filtered out of the results

  const placeSet = useMemo(() => new Set(places), [places]);

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
    setInvalidPlaces(new Set());
    if (!start.trim() || !end.trim()) {
      setError("יש לבחור נקודת מוצא ונקודת יעד.");
      return;
    }
    const via = vias.map((v) => v.trim()).filter(Boolean);
    // Only assert "unknown" once the place universe is actually loaded; an empty
    // set means the /api/places/ fetch hasn't landed yet (e.g. start/end were
    // prefilled from the URL), and flagging valid places then is a false error.
    const unknown = placeSet.size > 0 ? unknownPlaces([start.trim(), end.trim(), ...via], placeSet) : [];
    if (unknown.length > 0) {
      setInvalidPlaces(new Set(unknown));
      setError(unknownPlacesMessage(unknown));
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const data = await findPaths(start.trim(), end.trim(), via);
      setResult(data);
    } catch (e2) {
      setError(e2.message);
    } finally {
      setLoading(false);
    }
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
    invalidPlaces,
    hiddenTypes,
    presentTypes,
    submit,
    toggleType,
  };
}
