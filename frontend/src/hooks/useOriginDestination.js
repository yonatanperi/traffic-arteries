import { useUrlParam } from "./useUrlParam.js";

/**
 * Controlled origin/destination pair with a swap action, persisted to the
 * URL's `start`/`end` query params. Shared by every "from -> to" search field
 * (the home search form, the brain toolbar's path mode) so the swap behavior
 * stays identical everywhere it appears, and so a search built on one page
 * carries over when navigating to the other.
 */
export function useOriginDestination() {
  const [start, setStart] = useUrlParam("start");
  const [end, setEnd] = useUrlParam("end");

  function swap() {
    setStart(end);
    setEnd(start);
  }

  return { start, setStart, end, setEnd, swap };
}
