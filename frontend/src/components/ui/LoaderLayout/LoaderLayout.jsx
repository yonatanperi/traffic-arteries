import "./LoaderLayout.css";

/**
 * The single loading state used everywhere in the app: a big plain spinner,
 * no visible label, centered in whatever container it's placed in. Fills the
 * container's real height when the container provides one (page, canvas
 * area, flex region) and falls back to a comfortable min-height otherwise,
 * so it never renders as a tiny sliver stuck to the top of a block-level
 * parent. `label` stays screen-reader-only — sighted users get the spinner.
 */
export default function LoaderLayout({ label = "טוען…" }) {
  return (
    <div className="loader-layout" role="status" aria-live="polite">
      <span className="loader-layout-spinner" aria-hidden="true" />
      <span className="sr-only">{label}</span>
    </div>
  );
}
