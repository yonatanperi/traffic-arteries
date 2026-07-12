import { IconChevron } from "../../ui/icons";
import "./RouteChain.css";

/**
 * Static chain of stops: a row of pill "stops" joined by chevron connectors,
 * with the first/last stop accented as the route's endpoints. This is the
 * canonical route rendering used by the path results.
 *
 * props:
 *   stops      array of place names
 *   highlight  optional lowercased query; matching stops get a subtle ring
 */
export default function RouteChain({ stops, highlight }) {
  return (
    <ol className="chain">
      {stops.map((place, j) => {
        const matched = highlight && place.toLowerCase().includes(highlight);
        return (
          <li className="chain-item" key={j}>
            <span
              className={
                "stop" +
                (j === 0 ? " stop--start" : "") +
                (j === stops.length - 1 ? " stop--end" : "") +
                (matched ? " stop--match" : "")
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
