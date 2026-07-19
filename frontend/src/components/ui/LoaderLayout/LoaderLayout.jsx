import { IconNetwork } from "../icons/icons.jsx";
import "./LoaderLayout.css";

/**
 * Full, centered loading state: a bordered card with a spinning ring around an
 * icon and a status label. Shared by the app-wide server-wake gate and any
 * page's initial data fetch, so the two full-page loading moments look the same.
 */
export default function LoaderLayout({ label = "טוען…", icon: Icon = IconNetwork }) {
  return (
    <div className="loader-layout">
      <div className="loader-layout-card">
        <span className="loader-layout-spinner" aria-hidden="true">
          <Icon size={30} />
        </span>
        <p className="loader-layout-title" role="status" aria-live="polite">
          {label}
        </p>
      </div>
    </div>
  );
}
