import { useEffect, useState } from "react";
import GraphView from "../components/GraphView.jsx";
import Loader from "../components/Loader.jsx";
import EmptyState from "../components/EmptyState.jsx";
import { IconAlert, IconNetwork } from "../components/icons.jsx";
import { getGraph } from "../api/client.js";
import "./BrainPage.css";

export default function BrainPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getGraph()
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="page brain-page">
      <div className="page-header">
        <h1 className="page-title">הצצה למוח</h1>
        <p className="page-subtitle">
          רשת הצמתים החיה של המערכת. גררו צמתים, הגדילו ותנועעו, והעבירו את העכבר
          מעל מקום כדי להאיר את חיבוריו הישירים.
        </p>
      </div>

      {!loading && !error && data && (
        <div className="brain-stats">
          <span className="brain-stat">
            <strong>{data.nodes.length}</strong> מקומות
          </span>
          <span className="brain-stat">
            <strong>{data.links.length}</strong> חיבורים
          </span>
        </div>
      )}

      <div className="brain-canvas-wrap">
        {loading && <Loader label="בונה את הרשת…" />}
        {error && (
          <EmptyState
            icon={<IconAlert size={30} />}
            tone="danger"
            title="שגיאה בטעינת הגרף"
            message={error}
          />
        )}
        {!loading && !error && data && data.nodes.length === 0 && (
          <EmptyState
            icon={<IconNetwork size={30} />}
            title="הרשת ריקה"
            message="עדיין אין מסלולים. הוסיפו מסלולים בעמוד עריכת המסלולים כדי לראות את הרשת מתעוררת לחיים."
          />
        )}
        {!loading && !error && data && data.nodes.length > 0 && <GraphView data={data} />}
      </div>
    </div>
  );
}
