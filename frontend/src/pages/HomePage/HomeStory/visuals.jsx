/**
 * The home story's illustrations. Every one of them is a diagram of something
 * the router actually does — candidates being probed, a transfer being paid
 * for, a tier being enforced — so the motion explains rather than decorates.
 *
 * All inline SVG in the house style (components/ui/icons), all decorative:
 * the surrounding copy carries the meaning and these are aria-hidden.
 */

import CountUp from "./CountUp.jsx";
import { priorityLabel } from "../../../utils/priorities.js";

/* The four corridors share their endpoints and differ in the middle — the same
   shape the candidate pool has. Drawn faintly as the network, then probed one
   by one, then the winner locks in. */
const CANDIDATES = [
  "286,132 232,64 168,92 96,40 34,48",
  "286,132 214,136 150,150 78,116 34,48",
  "286,132 246,100 176,132 108,84 34,48",
];
const WINNER = "286,132 220,110 150,118 82,86 34,48";
const MESH_NODES = [
  [232, 64],
  [168, 92],
  [96, 40],
  [214, 136],
  [150, 150],
  [78, 116],
  [246, 100],
  [176, 132],
  [108, 84],
  [220, 110],
  [150, 118],
  [82, 86],
];

export function ScanVisual() {
  return (
    <svg className="scan" viewBox="0 0 320 180" aria-hidden="true" focusable="false">
      {/* The network itself, always present under the search. */}
      {[...CANDIDATES, WINNER].map((points) => (
        <polyline key={points} className="scan-mesh" points={points} />
      ))}
      {MESH_NODES.map(([x, y]) => (
        <circle key={`${x}-${y}`} className="scan-mesh-node" cx={x} cy={y} r="2.4" />
      ))}

      {/* Probes: each candidate corridor drawn and discarded in turn. */}
      {CANDIDATES.map((points, i) => (
        <polyline
          key={points}
          className="scan-probe"
          style={{ animationDelay: `${i * 0.55}s` }}
          points={points}
        />
      ))}

      {/* The one that survives scoring. */}
      <polyline className="scan-win" points={WINNER} />

      <circle className="scan-end" cx="286" cy="132" r="6" />
      <circle className="scan-end" cx="34" cy="48" r="6" />
      <circle className="scan-halo" cx="286" cy="132" r="6" />
      <circle className="scan-halo" cx="34" cy="48" r="6" />
    </svg>
  );
}

/** One lane of a two-lane comparison: a route line plus its caption. */
function Lane({ tone, caption, children }) {
  return (
    <div className={"lane lane--" + tone}>
      <svg className="lane-svg" viewBox="0 0 300 34" aria-hidden="true" focusable="false">
        {children}
      </svg>
      <p className="lane-caption">{caption}</p>
    </div>
  );
}

export function ConcentrationVisual() {
  return (
    <div className="lanes">
      {/* Three authored routes stitched together: every joint is a transfer,
          and every transfer is what the HHI charges for. */}
      <Lane tone="lose" caption="שלושה צירים · שני מעברים">
        <line className="lane-line lane-line--a" x1="284" y1="17" x2="196" y2="17" />
        <line className="lane-line lane-line--b" x1="196" y1="17" x2="112" y2="17" />
        <line className="lane-line lane-line--c" x1="112" y1="17" x2="16" y2="17" />
        <circle className="lane-transfer" cx="196" cy="17" r="7" />
        <circle className="lane-transfer" cx="112" cy="17" r="7" />
        <circle className="lane-dot lane-dot--muted" cx="284" cy="17" r="5" />
        <circle className="lane-dot lane-dot--muted" cx="16" cy="17" r="5" />
      </Lane>

      <Lane tone="win" caption="ציר אחד · ללא מעברים">
        <line className="lane-line lane-line--accent" x1="284" y1="17" x2="16" y2="17" />
        <circle className="lane-dot" cx="284" cy="17" r="5" />
        <circle className="lane-dot" cx="16" cy="17" r="5" />
      </Lane>
    </div>
  );
}

export function PriorityVisual() {
  return (
    <div className="lanes">
      {/* Shorter, and still loses: the tier is checked before any length is. */}
      <Lane tone="lose" caption={`${priorityLabel(3)} · קצר יותר`}>
        <line className="lane-line lane-line--muted" x1="284" y1="17" x2="104" y2="17" />
        <circle className="lane-dot lane-dot--muted" cx="284" cy="17" r="5" />
        <circle className="lane-dot lane-dot--muted" cx="104" cy="17" r="5" />
      </Lane>

      <Lane tone="win" caption={`${priorityLabel(0)} · הציר שיוצג`}>
        <line className="lane-line lane-line--accent" x1="284" y1="17" x2="16" y2="17" />
        <circle className="lane-dot" cx="284" cy="17" r="5" />
        <circle className="lane-dot" cx="16" cy="17" r="5" />
      </Lane>
    </div>
  );
}

const RING_R = 52;
const RING_C = 2 * Math.PI * RING_R;
const MATCH = 87;

export function MatchVisual({ run }) {
  return (
    <div className="match">
      <svg className="match-ring" viewBox="0 0 120 120" aria-hidden="true" focusable="false">
        <circle className="match-track" cx="60" cy="60" r={RING_R} />
        <circle
          className="match-value"
          cx="60"
          cy="60"
          r={RING_R}
          style={{
            // Wound fully back, then released to the score by the CSS animation
            // (which outranks these inline values while it runs and fills).
            strokeDasharray: RING_C,
            strokeDashoffset: RING_C,
            "--match-offset": RING_C * (1 - MATCH / 100),
          }}
        />
      </svg>
      {/* The number and its sign are one LTR run — as two elements in an RTL
          box the sign lands on the wrong side of the digits. */}
      <p className="match-num" dir="ltr">
        <CountUp value={MATCH} run={run} />
        <span className="match-pct">%</span>
      </p>
    </div>
  );
}

const RESULTS = [
  { title: "הציר המיטבי", match: 92 },
  { title: "ציר חלופי", match: 78 },
  { title: "ציר חלופי", match: 64 },
];

export function ResultsVisual() {
  return (
    <div className="stack" aria-hidden="true">
      {RESULTS.map((r, i) => (
        <div
          key={r.title + r.match}
          className={"stack-card" + (i === 0 ? " stack-card--best" : "")}
          style={{ animationDelay: `${0.12 + i * 0.14}s` }}
        >
          <span className="stack-title">{r.title}</span>
          <span className="stack-match">{r.match}%</span>
        </div>
      ))}
    </div>
  );
}
