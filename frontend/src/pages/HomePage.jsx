import { useEffect, useState } from "react";
import Autocomplete from "../components/Autocomplete.jsx";
import PathResults from "../components/PathResults.jsx";
import EmptyState from "../components/EmptyState.jsx";
import Loader from "../components/Loader.jsx";
import {
  IconOrigin,
  IconDestination,
  IconSwap,
  IconSearch,
  IconCompass,
  IconAlert,
  IconRoute,
  IconPlus,
  IconClose,
} from "../components/icons.jsx";
import { getPlaces, findPaths } from "../api/client.js";
import "./HomePage.css";

export default function HomePage() {
  const [places, setPlaces] = useState([]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [vias, setVias] = useState([]); // required intermediate stops
  const [result, setResult] = useState(null); // { paths } | null
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

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

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">לאן ניסע היום?</h1>
        <p className="page-subtitle">
          בחרו נקודת מוצא ויעד, ונמצא עבורכם את המסלולים הקצרים ביותר.
        </p>
      </div>

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

          <button
            type="button"
            className="swap-btn"
            onClick={swap}
            aria-label="החלף מוצא ויעד"
            title="החלף מוצא ויעד"
          >
            <IconSwap size={18} />
          </button>

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
                המסלול יעבור בכל העצירות, בסדר האופטימלי
              </span>
            </div>
          )}

          {vias.map((v, i) => (
            <div className="waypoint-row" key={i}>
              <Autocomplete
                icon={<IconRoute size={16} />}
                placeholder="תחנה שהמסלול חייב לעבור בה"
                options={places}
                value={v}
                onChange={(val) => setVia(i, val)}
              />
              <button
                type="button"
                className="waypoint-remove"
                onClick={() => removeVia(i)}
                aria-label="הסר עצירה"
                title="הסר עצירה"
              >
                <IconClose size={16} />
              </button>
            </div>
          ))}

          <button type="button" className="waypoint-add" onClick={addVia}>
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
          {loading ? "מחפש…" : "מצא מסלול"}
        </button>
      </form>

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <section className="results-area">
        {loading && <Loader label="מחשב מסלולים…" />}

        {!loading && result && result.paths.length === 0 && (
          <EmptyState
            icon={<IconAlert size={60} />}
            tone="warning"
            title="לא נמצא מסלול בין הנקודות"
            message="שתי הנקודות אינן מחוברות ברשת המסלולים הקיימת. נסו יעד אחר, או הוסיפו מסלול מקשר בעמוד עריכת המסלולים."
          />
        )}

        {!loading && result && result.paths.length > 0 && (
          <PathResults paths={result.paths} />
        )}

        {!loading && !result && !error && (
          <EmptyState
            icon={<IconCompass size={60} />}
            title="מוכנים לצאת לדרך"
            message="הזינו שתי נקודות למעלה כדי לגלות את המסלולים האפשריים ביניהן."
          />
        )}
      </section>
    </div>
  );
}
