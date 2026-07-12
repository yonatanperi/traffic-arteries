import { useEffect, useMemo, useRef, useState } from "react";
import RouteEditor from "../../components/RouteEditor";
import CompromisedEditor from "../../components/CompromisedEditor";
import Loader from "../../components/Loader";
import { IconRoute, IconAlert } from "../../components/icons";
import {
  getRoutes,
  saveRoutes,
  getCompromised,
  saveCompromised,
} from "../../api/client.js";
import "./RoutesPage.css";

const TABS = [
  {
    id: "routes",
    label: "עריכת צירים",
    icon: IconRoute,
    title: "עריכת צירים",
    subtitle:
      "בנו וערכו את רשת הצירים. כל ציר הוא שרשרת של תחנות; תחנות עוקבות " +
      "מחוברות זו לזו בשני הכיוונים. השינויים נשמרים אוטומטית.",
  },
  {
    id: "compromised",
    label: "יעדים מושבתים",
    icon: IconAlert,
    title: "יעדים מושבתים",
    subtitle:
      "סמנו יעדים שאינם זמינים באופן זמני, מקובצים לפי אירוע. יעד מושבת " +
      "לא יילקח בחשבון בחיפוש צירים, אך יישאר גלוי (מסומן באדום) במפת הרשת. " +
      "השינויים נשמרים אוטומטית.",
  },
];

export default function RoutesPage() {
  const [activeTab, setActiveTab] = useState("routes");

  const [routes, setRoutes] = useState(null);
  const [originalRoutes, setOriginalRoutes] = useState(null);
  const savingRoutesRef = useRef(Promise.resolve());

  const [compromised, setCompromised] = useState(null);
  const [originalCompromised, setOriginalCompromised] = useState(null);
  const savingCompromisedRef = useRef(Promise.resolve());

  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([getRoutes(), getCompromised()])
      .then(([routesData, compromisedData]) => {
        setRoutes(routesData);
        setOriginalRoutes(JSON.stringify(routesData));
        setCompromised(compromisedData);
        setOriginalCompromised(JSON.stringify(compromisedData));
      })
      .finally(() => setLoading(false));
  }, []);

  // Known place names across all routes -> autocomplete suggestions, and the
  // closed list of destinations the compromised tab picks from.
  const suggestions = useMemo(() => {
    if (!routes) return [];
    const set = new Set();
    routes.forEach((r) => r.forEach((p) => p.trim() && set.add(p.trim())));
    return [...set].sort((a, b) => a.localeCompare(b, "he"));
  }, [routes]);

  const compromisedPlaces = useMemo(() => {
    if (!compromised) return new Set();
    return new Set(compromised.flat());
  }, [compromised]);

  // Auto-save on every edit action. Each editor calls this instead of a plain
  // setState, so each add/remove immediately persists (when the result is
  // valid). Invalid intermediate states are held locally and saved as soon as
  // they become valid again.
  function applyRoutesChange(next) {
    setRoutes(next);

    const snapshot = JSON.stringify(next);
    if (snapshot === originalRoutes) return; // no net change vs. what's persisted
    if (next.some((r) => r.length < 2)) return; // wait until valid

    savingRoutesRef.current = savingRoutesRef.current
      .catch(() => {})
      .then(async () => {
        const saved = await saveRoutes(next);
        setOriginalRoutes(snapshot);
        setRoutes((cur) => (JSON.stringify(cur) === snapshot ? saved : cur));
      });
  }

  function applyCompromisedChange(next) {
    setCompromised(next);

    const snapshot = JSON.stringify(next);
    if (snapshot === originalCompromised) return;
    if (next.some((g) => g.length < 1)) return; // wait until every group has a destination

    savingCompromisedRef.current = savingCompromisedRef.current
      .catch(() => {})
      .then(async () => {
        const saved = await saveCompromised(next);
        setOriginalCompromised(snapshot);
        setCompromised((cur) =>
          JSON.stringify(cur) === snapshot ? saved : cur,
        );
      });
  }

  if (loading) {
    return (
      <div className="page">
        <Loader label="טוען נתונים…" />
      </div>
    );
  }

  const tab = TABS.find((t) => t.id === activeTab);

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">{tab.title}</h1>
        <p className="page-subtitle">{tab.subtitle}</p>
      </div>

      <div className="page-tabs" role="tablist" aria-label="עמוד עריכה">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={activeTab === id}
            className={"page-tab" + (activeTab === id ? " page-tab--on" : "")}
            onClick={() => setActiveTab(id)}
          >
            <Icon size={16} />
            {label}
          </button>
        ))}
      </div>

      {activeTab === "routes" ? (
        <RouteEditor
          routes={routes}
          onChange={applyRoutesChange}
          suggestions={suggestions}
          compromisedPlaces={compromisedPlaces}
        />
      ) : (
        <CompromisedEditor
          groups={compromised}
          onChange={applyCompromisedChange}
          suggestions={suggestions}
        />
      )}
    </div>
  );
}
