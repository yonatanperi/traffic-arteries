import { useEffect, useState } from "react";
import { getHealth } from "../../../api/client.js";
import Loader from "../../ui/Loader";
import "./ServerGate.css";

/**
 * Holds the app's content behind a single loader until the backend answers a
 * lightweight health probe. The backend runs on Render's free tier, which
 * spins down after ~15 min idle and takes tens of seconds to wake; without this
 * gate every page races that cold start and can misreport valid data as missing
 * (e.g. the home search flags real places as unknown before /api/places/ lands).
 *
 * Retries with capped backoff and never gives up — a cold start resolves once
 * the process is up, and a longer outage keeps the loader on screen rather than
 * dropping the user into a broken app.
 */
export default function ServerGate({ children }) {
  const [ready, setReady] = useState(false);
  const [slow, setSlow] = useState(false); // show the "waking up" note after a couple of misses

  useEffect(() => {
    let cancelled = false;
    let timer;

    async function ping(attempt) {
      try {
        await getHealth();
        if (!cancelled) setReady(true);
      } catch {
        if (cancelled) return;
        if (attempt >= 1) setSlow(true); // two misses ⇒ almost certainly a cold start
        const delay = Math.min(1000 * 2 ** attempt, 5000);
        timer = setTimeout(() => ping(attempt + 1), delay);
      }
    }

    ping(0);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  if (ready) return children;

  return (
    <div className="server-gate">
      <Loader label="מתחבר לשרת…" />
      {slow && (
        <p className="server-gate-note">
          השרת מתעורר ממצב שינה, זה עשוי לקחת עד דקה.
        </p>
      )}
    </div>
  );
}
