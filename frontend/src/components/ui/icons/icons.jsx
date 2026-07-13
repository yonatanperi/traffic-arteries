/**
 * Small stroke-based SVG icons (Feather-inspired). Each inherits `currentColor`
 * so it takes the surrounding text color. Size via the `size` prop.
 */

function Svg({ size = 18, children, filled = false, className, ...rest }) {
  return (
    <svg
      className={"ic" + (className ? " " + className : "")}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

// Origin — a target-style pin dot.
export function IconOrigin(props) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="2.6" fill="currentColor" stroke="none" />
    </Svg>
  );
}

// Destination — map pin.
export function IconDestination(props) {
  return (
    <Svg {...props}>
      <path d="M12 21s6.5-5.4 6.5-10.2A6.5 6.5 0 0 0 5.5 10.8C5.5 15.6 12 21 12 21Z" />
      <circle cx="12" cy="10.5" r="2.3" />
    </Svg>
  );
}

export function IconSwap(props) {
  return (
    <Svg {...props}>
      <path d="M7 4 3 8l4 4" />
      <path d="M3 8h13" />
      <path d="m17 20 4-4-4-4" />
      <path d="M21 16H8" />
    </Svg>
  );
}

export function IconCompass(props) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="m15.5 8.5-2 5-5 2 2-5 5-2Z" />
    </Svg>
  );
}

export function IconAlert(props) {
  return (
    <Svg {...props}>
      <path d="M10.3 3.7 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.7a2 2 0 0 0-3.4 0Z" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </Svg>
  );
}

export function IconNetwork(props) {
  return (
    <Svg {...props}>
      <circle cx="5" cy="6" r="2.2" />
      <circle cx="19" cy="7" r="2.2" />
      <circle cx="12" cy="18" r="2.2" />
      <path d="M6.9 7.2 10.6 16M17.2 8.6 13.2 16.3M7 6.4 17 6.8" />
    </Svg>
  );
}

export function IconPlus(props) {
  return (
    <Svg {...props}>
      <path d="M12 5v14M5 12h14" />
    </Svg>
  );
}

export function IconClose(props) {
  return (
    <Svg {...props}>
      <path d="M18 6 6 18M6 6l12 12" />
    </Svg>
  );
}

export function IconTrash(props) {
  return (
    <Svg {...props}>
      <path d="M3 6h18" />
      <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
      <path d="M6 6v14a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V6" />
      <path d="M10 11v6M14 11v6" />
    </Svg>
  );
}

export function IconCheck(props) {
  return (
    <Svg {...props}>
      <path d="M20 6 9 17l-5-5" />
    </Svg>
  );
}

export function IconChevron(props) {
  return (
    <Svg {...props}>
      <path d="m14 6-6 6 6 6" />
    </Svg>
  );
}

export function IconCopy(props) {
  return (
    <Svg {...props}>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M6 15H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1" />
    </Svg>
  );
}

export function IconSearch(props) {
  return (
    <Svg {...props}>
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </Svg>
  );
}

// Focus — crosshair for centering on a node.
export function IconFocus(props) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
    </Svg>
  );
}

// Fit — expand arrows to the four corners.
export function IconFit(props) {
  return (
    <Svg {...props}>
      <path d="M8 3H5a2 2 0 0 0-2 2v3" />
      <path d="M16 3h3a2 2 0 0 1 2 2v3" />
      <path d="M16 21h3a2 2 0 0 0 2-2v-3" />
      <path d="M8 21H5a2 2 0 0 1-2-2v-3" />
    </Svg>
  );
}

// Reset — circular refresh arrow.
export function IconReset(props) {
  return (
    <Svg {...props}>
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 3v5h5" />
    </Svg>
  );
}

export function IconPause(props) {
  return (
    <Svg {...props}>
      <rect x="6" y="5" width="4" height="14" rx="1" />
      <rect x="14" y="5" width="4" height="14" rx="1" />
    </Svg>
  );
}

export function IconPlay(props) {
  return (
    <Svg {...props}>
      <path d="M7 4.5v15l13-7.5-13-7.5Z" />
    </Svg>
  );
}

export function IconDownload(props) {
  return (
    <Svg {...props}>
      <path d="M12 3v12" />
      <path d="m7 10 5 5 5-5" />
      <path d="M4 20h16" />
    </Svg>
  );
}

// Insights — a lightbulb.
export function IconBulb(props) {
  return (
    <Svg {...props}>
      <path d="M9 18h6" />
      <path d="M10 21h4" />
      <path d="M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.3 1 2.5h6c0-1.2.3-1.8 1-2.5A6 6 0 0 0 12 3Z" />
    </Svg>
  );
}

// Route — path mode.
export function IconRoute(props) {
  return (
    <Svg {...props}>
      <circle cx="6" cy="19" r="2.4" />
      <circle cx="18" cy="5" r="2.4" />
      <path d="M8.4 19H14a3.5 3.5 0 0 0 0-7h-4a3.5 3.5 0 0 1 0-7h5.6" />
    </Svg>
  );
}

// Filter — a funnel.
export function IconFilter(props) {
  return (
    <Svg {...props}>
      <path d="M4 5h16l-6 7.5V18l-4 2v-7.5Z" />
    </Svg>
  );
}

// User — for identity fields (login/register personal id).
export function IconUser(props) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="8" r="3.6" />
      <path d="M4.5 20c1.4-3.6 4.4-5.5 7.5-5.5s6.1 1.9 7.5 5.5" />
    </Svg>
  );
}

// Lock — for password fields.
export function IconLock(props) {
  return (
    <Svg {...props}>
      <rect x="5" y="11" width="14" height="9" rx="2" />
      <path d="M8 11V7.5a4 4 0 0 1 8 0V11" />
    </Svg>
  );
}

// Eye — show password.
export function IconEye(props) {
  return (
    <Svg {...props}>
      <path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12Z" />
      <circle cx="12" cy="12" r="2.6" />
    </Svg>
  );
}

// Eye off — hide password.
export function IconEyeOff(props) {
  return (
    <Svg {...props}>
      <path d="M3 3l18 18" />
      <path d="M10.6 5.7A9.8 9.8 0 0 1 12 5.5c6.4 0 10 6.5 10 6.5a15 15 0 0 1-3.5 4.2M6.6 6.7A15.4 15.4 0 0 0 2 12s3.6 6.5 10 6.5a9.7 9.7 0 0 0 4.4-1" />
      <path d="M9.5 9.7A2.6 2.6 0 0 0 12 14.6" />
    </Svg>
  );
}

// Hub — a busy node, drawn as a star burst.
export function IconHub(props) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v4M12 18v4M2 12h4M18 12h4M5 5l2.5 2.5M16.5 16.5 19 19M19 5l-2.5 2.5M7.5 16.5 5 19" />
    </Svg>
  );
}
