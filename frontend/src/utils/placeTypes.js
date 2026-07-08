/**
 * Classifies a place name into a stop "type" based on naming conventions used
 * throughout the routes data (e.g. "צ. X" for a junction, "מ. X" / "מוצב X"
 * for a base).
 */

export const PLACE_TYPES = [
  { key: "junction", label: "צמתים", test: (name) => /^צ\.\s*\S/.test(name) },
  { key: "base", label: "בסיסים", test: (name) => /^(מ\.\s*|מוצב\s+)\S/.test(name) },
  { key: "interchange", label: "מחלפים", test: (name) => /^מחלף\s*\S/.test(name) },
];

/** Returns the matching PLACE_TYPES key for a place name, or null if none match. */
export function classifyPlace(name) {
  const trimmed = (name || "").trim();
  const type = PLACE_TYPES.find((t) => t.test(trimmed));
  return type ? type.key : null;
}
