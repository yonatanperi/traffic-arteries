import { useEffect, useMemo, useState } from "react";
import Autocomplete from "../../components/Autocomplete";
import PathResults from "../../components/PathResults";
import EmptyState from "../../components/EmptyState";
import Loader from "../../components/Loader";
import PageHeader from "../../components/PageHeader";
import SwapButton from "../../components/SwapButton";
import IconButton from "../../components/IconButton";
import Pill from "../../components/Pill";
import {
  IconOrigin,
  IconDestination,
  IconSearch,
  IconCompass,
  IconAlert,
  IconRoute,
  IconPlus,
  IconClose,
  IconFilter,
} from "../../components/icons";
import { getPlaces, findPaths } from "../../api/client.js";
import { PLACE_TYPES, classifyPlace } from "../../utils/placeTypes.js";
import "./HomePage.css";

export default function HomePage() {
  const [places, setPlaces] = useState([]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [vias, setVias] = useState([]); // required intermediate stops
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

  async function onSubmit(e) {
    e.preventDefault();
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

  function swap() {
    setStart(end);
    setEnd(start);
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

  return (
    <div className="page">
      <PageHeader title="לאן ניסע היום?" subtitle="בחרו נקודת מוצא ויעד, נבנה את ציר התנועה עבורכם." />

      <form className="search-panel card" onSubmit={onSubmit}>
        <div className="search-fields">
          <Autocomplete
            label="מוצא"
            icon={<IconOrigin size={17} />}
            placeholder="מקום המוצא"
            options={places}
            value={start}
            onChange={setStart}
          />

          <SwapButton onClick={swap} />

          <Autocomplete
            label="יעד"
            icon={<IconDestination size={17} />}
            placeholder="מקום היעד"
            options={places}
            value={end}
            onChange={setEnd}
          />
        </div>

        <div className="waypoints">
          {vias.length > 0 && (
            <div className="waypoints-head">
              <span className="waypoints-title">
                <IconRoute size={15} />
                עצירות ביניים
              </span>
              <span className="waypoints-hint">
                הציר יעבור בכל העצירות, בסדר האופטימלי
              </span>
            </div>
          )}

          {vias.map((v, i) => (
            <div className="waypoint-row" key={i}>
              <Autocomplete
                icon={<IconRoute size={16} />}
                placeholder="תחנה שהציר חייב לעבור בה"
                options={places}
                value={v}
                onChange={(val) => setVia(i, val)}
              />
              <IconButton
                size="lg"
                className="waypoint-remove"
                onClick={() => removeVia(i)}
                ariaLabel="הסר עצירה"
                title="הסר עצירה"
              >
                <IconClose size={16} />
              </IconButton>
            </div>
          ))}

          <button type="button" className="btn btn-dashed waypoint-add" onClick={addVia}>
            <IconPlus size={16} />
            הוסף עצירת ביניים
          </button>
        </div>

        <button
          type="submit"
          className="btn btn-primary search-submit"
          disabled={loading}
        >
          <IconSearch size={18} />
          {loading ? "מחפש…" : "בניית ציר תנועה"}
        </button>
      </form>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <section className="results-area">
        {loading && <Loader label="מחשב צירים…" />}

        {!loading && result && result.paths.length === 0 && (
          <EmptyState
            icon={<IconAlert size={60} />}
            tone="warning"
            title="לא נמצא ציר בין הנקודות"
            message="שתי הנקודות אינן מחוברות ברשת הצירים הקיימת. נסו יעד אחר, או הוסיפו ציר מקשר בעמוד עריכת הצירים."
          />
        )}

        {!loading && result && result.paths.length > 0 && (
          <>
            {presentTypes.size > 0 && (
              <div className="type-filters">
                <span className="type-filters-label">
                  <IconFilter size={24} />
                </span>
                {PLACE_TYPES.filter((t) => presentTypes.has(t.key)).map((t) => {
                  const active = !hiddenTypes.has(t.key);
                  return (
                    <Pill
                      as="button"
                      size="md"
                      key={t.key}
                      className={
                        "type-filter-chip" +
                        (active ? "" : " type-filter-chip--off")
                      }
                      aria-pressed={active}
                      onClick={() => toggleType(t.key)}
                    >
                      {t.label}
                    </Pill>
                  );
                })}
              </div>
            )}
            <PathResults
              paths={result.paths}
              meta={result.meta}
              hiddenTypes={hiddenTypes}
            />
          </>
        )}

        {!loading && !result && !error && (
          <EmptyState
            icon={<IconCompass size={60} />}
            title="מוכנים לצאת לדרך"
            message="הזינו שתי נקודות למעלה כדי לגלות את הצירים האפשריים ביניהן."
          />
        )}
      </section>
    </div>
  );
}
