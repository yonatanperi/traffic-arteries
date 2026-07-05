import { useEffect, useMemo, useState } from "react";
import RouteEditor from "../components/RouteEditor.jsx";
import Loader from "../components/Loader.jsx";
import { IconCheck } from "../components/icons.jsx";
import { getRoutes, saveRoutes } from "../api/client.js";
import "./RoutesPage.css";

export default function RoutesPage() {
  const [routes, setRoutes] = useState(null);
  const [original, setOriginal] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState(null); // {type, text}

  useEffect(() => {
    getRoutes()
      .then((data) => {
        setRoutes(data);
        setOriginal(JSON.stringify(data));
      })
      .catch((e) => setStatus({ type: "error", text: e.message }))
      .finally(() => setLoading(false));
  }, []);

  const dirty = routes !== null && JSON.stringify(routes) !== original;

  // Known place names across all routes -> datalist suggestions.
  const suggestions = useMemo(() => {
    if (!routes) return [];
    const set = new Set();
    routes.forEach((r) => r.forEach((p) => p.trim() && set.add(p.trim())));
    return [...set].sort((a, b) => a.localeCompare(b, "he"));
  }, [routes]);

  const invalid = routes ? routes.filter((r) => r.length < 2).length : 0;

  async function onSave() {
    setStatus(null);
    setSaving(true);
    try {
      const saved = await saveRoutes(routes);
      setRoutes(saved);
      setOriginal(JSON.stringify(saved));
      setStatus({ type: "success", text: "המסלולים נשמרו והגרף נבנה מחדש." });
    } catch (e) {
      setStatus({ type: "error", text: e.message });
    } finally {
      setSaving(false);
    }
  }

  function onReset() {
    setRoutes(JSON.parse(original));
    setStatus(null);
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
          מחוברות זו לזו בשני הכיוונים.
        </p>
      </div>

      {status && (
        <div className={"status-banner status-banner--" + status.type} role="alert">
          {status.text}
        </div>
      )}

      <RouteEditor routes={routes} onChange={setRoutes} suggestions={suggestions} />

      <div className={"save-bar" + (dirty ? " save-bar--active" : "")}>
        <div className="save-bar-info">
          {invalid > 0 ? (
            <span className="save-bar-warn">
              {invalid} מסלולים עם פחות משתי תחנות — יש להשלים לפני שמירה
            </span>
          ) : dirty ? (
            <span>יש שינויים שלא נשמרו</span>
          ) : (
            <span className="save-bar-clean">
              <IconCheck size={15} /> הכול שמור
            </span>
          )}
        </div>
        <div className="save-bar-actions">
          <button
            type="button"
            className="btn btn-ghost"
            onClick={onReset}
            disabled={!dirty || saving}
          >
            בטל שינויים
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={onSave}
            disabled={!dirty || saving || invalid > 0}
          >
            {saving ? "שומר…" : "שמור שינויים"}
          </button>
        </div>
      </div>
    </div>
  );
}
