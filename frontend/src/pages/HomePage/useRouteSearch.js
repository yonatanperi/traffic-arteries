import { useEffect, useMemo, useState } from "react";
import { getPlaces, findPaths } from "../../api/client.js";
import { classifyPlace, DEFAULT_GROUP } from "../../utils/placeGroups.js";
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
  const [hiddenTypes, setHiddenTypes] = useState(() => new Set(["camp", "post"])); // stop types filtered out of the results
  const [didSearch, setDidSearch] = useState(false); // a search is dispatched/showing (drives the phone fold)
  const placeSet = useMemo(() => new Set(places), [places]);

  // Only interior stops are ever filtered (start/end are always kept), so a
  // filter chip is only worth showing if some route actually has one of that
  // type among its interior stops. "אחר" never gets a chip at all — it must
  // always stay visible — so it's excluded here too, not just at render time.
  const presentTypes = useMemo(() => {
    const set = new Set();
    if (!result) return set;
    result.paths.forEach((path) => {
      path.forEach((place, i) => {
        if (i === 0 || i === path.length - 1) return;
        const type = classifyPlace(place);
        if (type !== DEFAULT_GROUP) set.add(type);
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
    // Fold the form as the request goes out, not when it lands, so the loader
    // appears where the results will. Validation failures above never get here,
    // so a rejected query keeps the fields on screen to be fixed.
    setDidSearch(true);
    try {
      const data = await findPaths(start.trim(), end.trim(), via);
      setResult(data);
    } catch (e2) {
      setError(e2.message);
      setDidSearch(false); // nothing to show — hand the form back
    } finally {
      setLoading(false);
    }
  }

  // Leaving the results (the phone trip bar's back arrow): the page goes back to
  // how it looked before the search — the form, still filled in, over the idle
  // home content — rather than the form stacked on top of the results it came
  // from. The query itself (start/end/vias) is deliberately kept so "back" means
  // "edit this search", not "start over".
  function reopenSearch() {
    setResult(null);
    setError("");
    setDidSearch(false);
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
    didSearch,
    reopenSearch,
    submit,
    toggleType,
  };
}
