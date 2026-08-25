/**
 * Route priority: an int 0..3 on the wire (0 = best), Hebrew letters in the UI.
 *
 * The backend never sees a letter and the UI never shows a digit, so this module
 * is the only place the two vocabularies meet — the same role placeGroups.js plays
 * for place "types". Anything rendering a priority goes through here.
 */

export const BEST_PRIORITY = 0;

/** Priority value -> its Hebrew ordinal letter. Index *is* the wire value. */
export const PRIORITY_LETTERS = ["א׳", "ב׳", "ג׳", "ד׳"];

/** The letter for a priority, falling back to the best one if it's out of range. */
export function priorityLetter(priority) {
  return PRIORITY_LETTERS[priority] ?? PRIORITY_LETTERS[BEST_PRIORITY];
}

/** Full label, e.g. `עדיפות ב׳`. */
export function priorityLabel(priority) {
  return `עדיפות ${priorityLetter(priority)}`;
}

/**
 * Every selectable priority, in order — feeds every priority picker in the routes
 * editor (a plain route's, and each head of a branched one). The label carries the
 * whole phrase (`עדיפות א׳`), so the control reads as one unit rather than a bare
 * letter sitting next to a separate caption.
 */
// `priority` doubles `value`; it's the field every renderer reads for the dot and
// the letter, so an option always carries what it *shows* under one name.
export const PRIORITY_OPTIONS = PRIORITY_LETTERS.map((_, value) => ({
  value,
  priority: value,
  label: priorityLabel(value),
}));

/**
 * Whether a priority is worth calling out. Best priority is the default and the
 * overwhelmingly common case — badging it everywhere would be noise, so callers
 * only surface a priority that actually cost the route something.
 */
export function isDowngraded(priority) {
  return typeof priority === "number" && priority > BEST_PRIORITY;
}
