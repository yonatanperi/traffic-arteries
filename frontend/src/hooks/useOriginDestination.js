import { useGetUrlParams, useSetUrlParams } from "./useUrlParams.js";

/**
 * Controlled origin/destination pair with a swap action, persisted to the
 * URL's `start`/`end` query params. Shared by every "from -> to" search field
 * (the home search form, the brain toolbar's path mode) so the swap behavior
 * stays identical everywhere it appears, and so a search built on one page
 * carries over when navigating to the other.
 */
export function useOriginDestination() {
  const { getParam } = useGetUrlParams();
  const { setParams } = useSetUrlParams();
  const start = getParam("start");
  const end = getParam("end");

  function setStart(value) {
    setParams({ start: value });
  }
  function setEnd(value) {
    setParams({ end: value });
  }
  function swap() {
    setParams({ start: end, end: start });
  }

  return { start, setStart, end, setEnd, swap };
}
