import { useEffect, useMemo, useRef, useState } from "react";
import RouteEditor from "../components/RouteEditor.jsx";
import Loader from "../components/Loader.jsx";
import { getRoutes, saveRoutes } from "../api/client.js";
import "./RoutesPage.css";

export default function RoutesPage() {
  const [routes, setRoutes] = useState(null);
  const [original, setOriginal] = useState(null);
  const [loading, setLoading] = useState(true);
  // Serializes saves so overlapping actions persist in order.
  const savingRef = useRef(Promise.resolve());

  useEffect(() => {
    getRoutes()
      .then((data) => {
        setRoutes(data);
        setOriginal(JSON.stringify(data));
      })
      .finally(() => setLoading(false));
  }, []);

  // Known place names across all routes -> autocomplete suggestions.
  const suggestions = useMemo(() => {
    if (!routes) return [];
    const set = new Set();
    routes.forEach((r) => r.forEach((p) => p.trim() && set.add(p.trim())));
    return [...set].sort((a, b) => a.localeCompare(b, "he"));
  }, [routes]);

  // Auto-save on every edit action. RouteEditor calls this instead of a plain
  // setState, so each add/remove immediately persists (when the result is
  // valid). Invalid intermediate states (e.g. a brand-new empty route) are
  // held locally and saved as soon as they become valid again.
  function applyChange(next) {
    setRoutes(next);

    const snapshot = JSON.stringify(next);
    if (snapshot === original) return; // no net change vs. what's persisted
    if (next.some((r) => r.length < 2)) return; // wait until valid

    savingRef.current = savingRef.current
      .catch(() => {})
      .then(async () => {
        const saved = await saveRoutes(next);
        setOriginal(snapshot);
        // Adopt the server's normalized copy only if nothing changed since.
        setRoutes((cur) => (JSON.stringify(cur) === snapshot ? saved : cur));
      });
  }

  if (loading) {
    return (
      <div className="page">
        <Loader label="טוען מסלולים…" />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">עריכת מסלולים</h1>
        <p className="page-subtitle">
          בנו וערכו את רשת המסלולים. כל מסלול הוא שרשרת של תחנות; תחנות עוקבות
          מחוברות זו לזו בשני הכיוונים. השינויים נשמרים אוטומטית.
        </p>
      </div>

      <RouteEditor routes={routes} onChange={applyChange} suggestions={suggestions} />
    </div>
  );
}
