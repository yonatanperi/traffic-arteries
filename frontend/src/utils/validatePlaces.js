/**
 * Which of the given place names aren't in the known-places list. Used to
 * flag a typed start/end/waypoint as an unknown place before ever calling
 * `/api/path/` — otherwise an unknown place just looks like "no route found",
 * which is a different problem (existing places that aren't connected).
 */
export function unknownPlaces(names, known) {
  const knownSet = known instanceof Set ? known : new Set(known);
  const seen = new Set();
  return names.filter((n) => n && !knownSet.has(n) && !seen.has(n) && seen.add(n));
}

export function unknownPlacesMessage(names) {
  if (names.length === 0) return "";
  if (names.length === 1) return `המקום "${names[0]}" אינו קיים ברשת הצירים.`;
  const list = names.map((n) => `"${n}"`).join(", ");
  return `המקומות ${list} אינם קיימים ברשת הצירים.`;
}
