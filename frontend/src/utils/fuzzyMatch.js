/**
 * Typo- and punctuation-tolerant matching for place names against a search
 * query. Place names mix straight quotes/apostrophes with Hebrew gershayim
 * (״) and geresh (׳), dots, hyphens and inconsistent spacing (e.g. `אוגמ"ר
 * 80` vs `מ. סנטג׳ין`), so a plain substring check misses a lot of otherwise
 * obvious matches.
 */

const NIQQUD_RE = /[֑-ׇ]/g;
const QUOTE_RE = /["“”„״´`]/g;
const GERESH_RE = /['’‘׳]/g;
const DASH_RE = /[-–—־]/g;

/** Lowercases and unifies visually-equivalent quote/dash characters. */
function normalize(s) {
  return s
    .replace(NIQQUD_RE, "")
    .replace(QUOTE_RE, '"')
    .replace(GERESH_RE, "'")
    .replace(DASH_RE, "-")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

/** Drops punctuation entirely, so a missing/extra quote or dot still matches. */
function stripPunct(s) {
  return s
    .replace(/["'\-./()]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Minimum edit distance between `pattern` and its best-aligned substring of
 * `text` (free start/end) — i.e. how close is the nearest typo'd occurrence.
 */
function approxSubstringEditDistance(pattern, text) {
  const m = pattern.length;
  const n = text.length;
  if (m === 0) return 0;
  let prev = new Array(n + 1).fill(0); // dp[0][j] = 0: substring can start anywhere
  for (let i = 1; i <= m; i++) {
    const curr = new Array(n + 1);
    curr[0] = i;
    for (let j = 1; j <= n; j++) {
      const cost = pattern[i - 1] === text[j - 1] ? 0 : 1;
      curr[j] = Math.min(
        prev[j] + 1, // delete from pattern
        curr[j - 1] + 1, // insert into pattern
        prev[j - 1] + cost // match/substitute
      );
    }
    prev = curr;
  }
  return Math.min(...prev); // dp[m][*]: substring can end anywhere
}

/**
 * Scores how well `option` matches `query`. Higher is better; -1 means no
 * match. Tiers (exact > prefix > substring > fuzzy) so close/typo'd matches
 * never outrank a plain substring hit.
 */
export function matchScore(query, option) {
  const qNorm = normalize(query);
  if (!qNorm) return 0;
  const oNorm = normalize(option);

  if (oNorm === qNorm) return 1000;
  if (oNorm.startsWith(qNorm)) return 900 - (oNorm.length - qNorm.length);

  const qStrip = stripPunct(qNorm);
  const oStrip = stripPunct(oNorm);

  if (oStrip.startsWith(qStrip)) return 850 - (oStrip.length - qStrip.length);

  const idx = oNorm.indexOf(qNorm);
  if (idx !== -1) return 750 - idx;

  const idxStrip = oStrip.indexOf(qStrip);
  if (idxStrip !== -1) return 700 - idxStrip;

  if (oStrip.split(" ").some((token) => token.startsWith(qStrip))) return 650;

  // Typo tolerance: only once nothing precise matched, and only for queries
  // long enough that a bounded edit distance is still meaningful.
  if (qStrip.length >= 3) {
    const maxAllowed = Math.max(1, Math.round(qStrip.length * 0.25));
    const dist = approxSubstringEditDistance(qStrip, oStrip);
    if (dist <= maxAllowed) return 500 - dist * 20;
  }

  return -1;
}

/** Ranks `options` against `query`, best matches first. */
export function fuzzyFilter(options, query, limit = 8) {
  const trimmed = query.trim();
  if (!trimmed) return options.slice(0, limit);
  return options
    .map((option) => ({ option, score: matchScore(trimmed, option) }))
    .filter(({ score }) => score > 0)
    .sort((a, b) => b.score - a.score || a.option.length - b.option.length)
    .slice(0, limit)
    .map(({ option }) => option);
}
