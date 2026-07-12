import { useEffect, useMemo, useState } from "react";
import RouteEditor from "../../components/routes/RouteEditor";
import CompromisedEditor from "../../components/routes/CompromisedEditor";
import Loader from "../../components/ui/Loader";
import PageHeader from "../../components/ui/PageHeader";
import Page from "../../components/layout/Page";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import { IconRoute, IconAlert } from "../../components/ui/icons";
import { useAutoSave } from "../../hooks/useAutoSave.js";
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
      "סמנו יעדים שאינם זמינים באופן זמני, מקובצים לפי אירוע / סיבה. " +
      "השינויים נשמרים אוטומטית.",
  },
];

export default function RoutesPage() {
  const [activeTab, setActiveTab] = useState("routes");
  const [loading, setLoading] = useState(true);

  // Auto-save on every edit action. Each editor calls the hook's `apply`
  // instead of a plain setState, so each add/remove immediately persists
  // (when the result is valid). Invalid intermediate states are held locally
  // and saved as soon as they become valid again.
  const routesState = useAutoSave(saveRoutes, (r) => r.every((route) => route.length >= 2));
  const compromisedState = useAutoSave(saveCompromised, (g) => g.every((group) => group.length >= 1));

  useEffect(() => {
    Promise.all([getRoutes(), getCompromised()])
      .then(([routesData, compromisedData]) => {
        routesState.seed(routesData);
        compromisedState.seed(compromisedData);
      })
      .finally(() => setLoading(false));
  }, []);

  const routes = routesState.value;
  const compromised = compromisedState.value;

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

  if (loading) {
    return (
      <Page>
        <Loader label="טוען נתונים…" />
      </Page>
    );
  }

  const tab = TABS.find((t) => t.id === activeTab);

  return (
    <Page>
      <PageHeader title={tab.title} subtitle={tab.subtitle} />

      <SegmentedControl
        ariaLabel="עמוד עריכה"
        value={activeTab}
        onChange={setActiveTab}
        className="page-tabs"
        items={TABS.map(({ id, label, icon: Icon }) => ({
          value: id,
          icon: <Icon size={16} />,
          label,
        }))}
      />

      {activeTab === "routes" ? (
        <RouteEditor
          routes={routes}
          onChange={routesState.apply}
          suggestions={suggestions}
          compromisedPlaces={compromisedPlaces}
        />
      ) : (
        <CompromisedEditor
          groups={compromised}
          onChange={compromisedState.apply}
          suggestions={suggestions}
        />
      )}
    </Page>
  );
}
