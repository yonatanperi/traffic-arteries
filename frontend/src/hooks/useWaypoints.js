import { useGetUrlParams, useSetUrlParams } from "./useUrlParams.js";

/**
 * Controlled list of required intermediate stops, persisted to the URL's
 * repeated `via` query param. Shared by every path-search form (the home
 * search form, the brain toolbar's path mode) so a waypoint list built on
 * one page carries over when navigating to the other.
 */
export function useWaypoints() {
  const { getParam } = useGetUrlParams();
  const { setParams } = useSetUrlParams();
  const vias = getParam("via", { list: true });

  function addVia() {
    setParams({ via: [...vias, ""] });
  }
  function setVia(index, value) {
    setParams({ via: vias.map((x, i) => (i === index ? value : x)) });
  }
  function removeVia(index) {
    setParams({ via: vias.filter((_, i) => i !== index) });
  }

  return { vias, addVia, setVia, removeVia };
}
