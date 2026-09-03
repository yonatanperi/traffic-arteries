import { IconChevron } from "../../ui/icons";
import "./RouteChain.css";

/**
 * Static chain of stops: a row of pill "stops" joined by chevron connectors,
 * with the first/last stop accented as the route's endpoints. This is the
 * canonical route rendering used by the path results.
 *
 * props:
 *   stops             array of place names
 *   highlight         optional lowercased query; matching stops get a subtle ring
 *   highlightedStops  optional Set<string> of place names to ring in info-blue
 *                     (distinct from `highlight`'s search ring) — used by
 *                     PathResults when hovering a subroute chip. Matched by
 *                     place name, not index, since `stops` may already be a
 *                     type-filtered subset of the full path.
 *   endpoints         which terminal stops are the *route's* endpoints and get the
 *                     accent: "both" (default), "start", "end" or "none". A chain
 *                     rendered as one segment of a trip split at its waypoints ends
 *                     where the waypoint band begins, so its inner terminals are
 *                     mid-route stops — accenting them would claim the trip starts
 *                     or ends there. See <SegmentedRouteChain>.
 */
export default function RouteChain({
  stops,
  highlight,
  highlightedStops,
  endpoints = "both",
}) {
  const accentStart = endpoints === "both" || endpoints === "start";
  const accentEnd = endpoints === "both" || endpoints === "end";
  return (
    <ol className="chain">
      {stops.map((place, j) => {
        const matched = highlight && place.toLowerCase().includes(highlight);
        const infoMatched = highlightedStops && highlightedStops.has(place);
        return (
          <li className="chain-item" key={j}>
            <span
              className={
                "stop" +
                (accentStart && j === 0 ? " stop--start" : "") +
                (accentEnd && j === stops.length - 1 ? " stop--end" : "") +
                (matched ? " stop--match" : "") +
                (infoMatched ? " stop--info" : "")
              }
            >
              {place}
            </span>
            {j < stops.length - 1 && (
              <span className="chain-arrow" aria-hidden="true">
                <IconChevron size={15} />
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
