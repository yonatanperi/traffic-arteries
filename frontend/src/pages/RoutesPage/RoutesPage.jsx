import { useEffect, useMemo, useRef, useState } from "react";
import RouteEditor from "../../components/routes/RouteEditor";
import CompromisedEditor from "../../components/routes/CompromisedEditor";
import LoaderLayout from "../../components/ui/LoaderLayout";
import PageHeader from "../../components/ui/PageHeader";
import Page from "../../components/layout/Page";
import Button from "../../components/ui/Button";
import { SegmentedControl } from "../../components/ui/SegmentedControl";
import {
  IconRoute,
  IconAlert,
  IconUndo,
  IconRedo,
} from "../../components/ui/icons";
import { useAutoSave } from "../../hooks/useAutoSave.js";
import { routeStops, isRouteValid } from "../../utils/branches.js";
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
  const routesState = useAutoSave(saveRoutes, (r) => r.every(isRouteValid));
  const compromisedState = useAutoSave(saveCompromised, (g) =>
    g.every((group) => group.length >= 1),
  );

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

  // Undo/redo act on the tab you're looking at: each editor keeps its own
  // history, so a keystroke here can never rewrite data on the other tab.
  const editor = activeTab === "routes" ? routesState : compromisedState;
  // The hook returns fresh closures every render; a ref lets the keydown
  // listener stay registered once while always calling the current ones.
  const editorRef = useRef(editor);
  editorRef.current = editor;

  useEffect(() => {
    function onKey(e) {
      if (!e.ctrlKey && !e.metaKey) return;
      const key = e.key.toLowerCase();
      if (key !== "z" && key !== "y") return;
      // Inside a text field, Ctrl+Z belongs to the browser's own text undo —
      // stealing it would wipe the route list mid-typing. And don't edit behind
      // an open dialog (the rename confirmation).
      if (e.target.closest?.("input, textarea, [contenteditable='true']")) return;
      if (document.querySelector('[role="dialog"]')) return;

      e.preventDefault();
      const { undo, redo } = editorRef.current;
      if (key === "y" || e.shiftKey) redo();
      else undo();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // Known place names across all routes -> autocomplete suggestions, and the
  // closed list of destinations the compromised tab picks from.
  const suggestions = useMemo(() => {
    if (!routes) return [];
    const set = new Set();
    routes.forEach((r) =>
      routeStops(r).forEach((p) => p.trim() && set.add(p.trim())),
    );
    return [...set].sort((a, b) => a.localeCompare(b, "he"));
  }, [routes]);

  const compromisedPlaces = useMemo(() => {
    if (!compromised) return new Set();
    return new Set(compromised.flat());
  }, [compromised]);

  if (loading) {
    return (
      <Page>
        <LoaderLayout label="טוען נתונים…" />
      </Page>
    );
  }

  const tab = TABS.find((t) => t.id === activeTab);

  return (
    <Page>
      <PageHeader title={tab.title} subtitle={tab.subtitle} />

      <div className="routes-toolbar">
        <SegmentedControl
          ariaLabel="עמוד עריכה"
          value={activeTab}
          onChange={setActiveTab}
          items={TABS.map(({ id, label, icon: Icon }) => ({
            value: id,
            icon: <Icon size={16} />,
            label,
          }))}
        />

        <div className="routes-history">
          <Button
            variant="ghost"
            size="sm"
            onClick={editor.undo}
            disabled={!editor.canUndo}
            title="בטל את השינוי האחרון (Ctrl+Z)"
          >
            <IconUndo size={16} />
            בטל
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={editor.redo}
            disabled={!editor.canRedo}
            title="בצע שוב את השינוי שבוטל (Ctrl+Shift+Z)"
          >
            <IconRedo size={16} />
            בצע שוב
          </Button>
        </div>
      </div>

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
