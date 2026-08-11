import { useEffect, useState } from "react";

/**
 * Subscribe to a CSS media query from JS.
 *
 * For anything CSS can express on its own, use a `@media` rule instead — this
 * is for the cases where the *markup* differs per breakpoint, not just its
 * styling (the home page folds its search form into a summary bar on phones,
 * which is a different tree, not a restyled one).
 */
export function useMediaQuery(query) {
  const [matches, setMatches] = useState(
    () => window.matchMedia(query).matches,
  );

  useEffect(() => {
    const mql = window.matchMedia(query);
    setMatches(mql.matches); // the query may have changed since the last render
    const onChange = (e) => setMatches(e.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

/** The app-wide phone breakpoint — must track `max-width: 640px` in the CSS. */
export function useIsPhone() {
  return useMediaQuery("(max-width: 640px)");
}
