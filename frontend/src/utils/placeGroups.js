/**
 * The eight place groups (מחנה/מוצב/צומת/מחלף/שטח אש/כביש/מחסום/אחר), each with
 * a display prefix. The backend always sends/receives the full display string (e.g.
 * "צ. גומא") — a place's group is never a separate field on the wire, so this
 * module classifies purely by reading a name's own prefix back, the same way
 * everywhere in the app that needs a place's group does it.
 *
 * `test` here should stay conceptually aligned with `backend/api/place_groups.py`'s
 * `PREFIX_PATTERNS` — both parse the same real-world strings — though drift
 * here is lower-stakes than it would be for stored data: the worst case is a
 * misclassification for filtering/search, or an unnecessary/missing
 * "assign a group" prompt when adding a stop, never data corruption (the
 * backend is the sole authority for what actually gets persisted).
 */

export const DEFAULT_GROUP = "other";

export const PLACE_GROUPS = [
  { key: "camp", label: "מחנה", prefix: "מ.", test: /^מ(?:\.\s*|\s+)(?=\S)/ },
  { key: "post", label: "מוצב", prefix: "מוצב", test: /^מוצב\s+(?=\S)/ },
  { key: "junction", label: "צומת", prefix: "צ.", test: /^צ(?:\.\s*|\s+)(?=\S)/ },
  { key: "interchange", label: "מחלף", prefix: "מחלף", test: /^מחלף\s*(?=\S)/ },
  { key: "firing_zone", label: "שטח אש", prefix: "ש.א", test: /^ש[.\s]?א\s*(?=\S)/ },
  { key: "road", label: "כביש", prefix: "כביש", test: /^כביש\s+(?=\S)/ },
  { key: "checkpoint", label: "מחסום", prefix: "מחסום", test: /^מחסום\s+(?=\S)/ },
  { key: DEFAULT_GROUP, label: "אחר", prefix: null, test: null },
];

const BY_KEY = new Map(PLACE_GROUPS.map((g) => [g.key, g]));

/** The group a display/typed name's own prefix implies — always a real group
 * key, "אחר" (never null) when nothing matches. */
export function classifyPlace(name) {
  const trimmed = (name || "").trim();
  const group = PLACE_GROUPS.find((g) => g.test && g.test.test(trimmed));
  return group ? group.key : DEFAULT_GROUP;
}

/** Strip a *recognized* (non-"אחר") prefix off typed text, returning
 * `{ group, baseName }`, or `null` if nothing matches — the caller (the route
 * editor's new-stop flow) must ask the user for a group in that case, rather
 * than silently defaulting to "אחר". */
export function parseTypedPlace(text) {
  const trimmed = (text || "").trim();
  for (const g of PLACE_GROUPS) {
    if (g.test && g.test.test(trimmed)) {
      return { group: g.key, baseName: trimmed.replace(g.test, "").trim() };
    }
  }
  return null;
}

/** The full display string for a base name + group — used to *construct* a
 * stop's committed text after the user picks a group in the ask-popover, the
 * same as if they'd typed the prefix themselves. */
export function formatPlace(baseName, groupKey) {
  const group = BY_KEY.get(groupKey);
  return group?.prefix ? `${group.prefix} ${baseName}` : baseName;
}

export function groupLabel(key) {
  return (BY_KEY.get(key) ?? BY_KEY.get(DEFAULT_GROUP)).label;
}

/** Fixed categorical palette for BrainPage's "color by group" node-fill mode
 * (see GraphView.jsx) — kept here so the graph and its legend never drift. */
export const GROUP_COLORS = {
  camp: "#fb923c",
  post: "#c084fc",
  junction: "#4ade80",
  interchange: "#facc15",
  firing_zone: "#f87171",
  road: "#60a5fa",
  checkpoint: "#e879f9",
  other: "#94a3b8",
};
