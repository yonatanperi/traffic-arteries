import { useState } from "react";

/**
 * Controlled origin/destination pair with a swap action. Shared by every
 * "from -> to" search field (the home search form, the brain toolbar's path
 * mode) so the swap behavior stays identical everywhere it appears.
 */
export function useOriginDestination(initialStart = "", initialEnd = "") {
  const [start, setStart] = useState(initialStart);
  const [end, setEnd] = useState(initialEnd);

  function swap() {
    setStart(end);
    setEnd(start);
  }

  return { start, setStart, end, setEnd, swap };
}
