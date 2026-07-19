import { useEffect, useState } from "react";
import { getHealth } from "../../../api/client.js";
import { IconNetwork } from "../../ui/icons/icons.jsx";
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

  useEffect(() => {
    let cancelled = false;
    let timer;

    async function ping(attempt) {
      try {
        await getHealth();
        if (!cancelled) setReady(true);
      } catch {
        if (cancelled) return;
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
      <div className="server-gate-card">
        <span className="server-gate-spinner" aria-hidden="true">
          <IconNetwork size={30} />
        </span>
        <p className="server-gate-title" role="status" aria-live="polite">
          מתחברים לשרת…
        </p>
      </div>
    </div>
  );
}
