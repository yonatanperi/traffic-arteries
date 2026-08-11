import "./Logo.css";

/**
 * The app mark: the route trace from the home page's idle scanner
 * (pages/HomePage/IdleBanner) set inside a ring — the same glyph the product
 * already draws for itself, at badge size.
 *
 * Decorative by default: every caller so far wraps it in a link that carries
 * the accessible name.
 */
export default function Logo({ size = 34, className }) {
  return (
    <svg
      className={"logo" + (className ? " " + className : "")}
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <circle className="logo-ring" cx="20" cy="20" r="18" />
      {/* IdleBanner's polyline, scaled from its 200-unit box to 40. */}
      <polyline
        className="logo-trace"
        points="9.2,26.4 16.8,19.2 24,22 30.8,13.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle className="logo-node" cx="9.2" cy="26.4" r="2.6" />
      <circle className="logo-node" cx="30.8" cy="13.6" r="2.6" />
    </svg>
  );
}
