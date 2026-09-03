import { IconChevron, IconPin } from "../../ui/icons";
import RouteChain from "./RouteChain.jsx";
import { classifyPlace, DEFAULT_GROUP } from "../../../utils/placeGroups.js";
import "./SegmentedRouteChain.css";

/**
 * Filter a chain by stop type. The chain's own first and last are always kept;
 * only interior stops are subject to filtering. "אחר" is never hidden, regardless
 * of hiddenTypes' contents — it has no filter chip to toggle it off in the first
 * place (ResultsArea.jsx).
 *
 * Applied per *segment*, which is what keeps every waypoint on screen no matter
 * what is filtered: a segment ends where a waypoint begins, so the stop next to
 * each waypoint is a terminal and survives, and the waypoint itself is not in any
 * segment at all — it is its own band.
 */
export function visiblePath(path, hiddenTypes) {
  if (!hiddenTypes || hiddenTypes.size === 0) return path;
  return path.filter((place, i) => {
    if (i === 0 || i === path.length - 1) return true;
    const type = classifyPlace(place);
    return type === DEFAULT_GROUP || !hiddenTypes.has(type);
  });
}

/**
 * Cut a result chain into what actually gets rendered: alternating segment and
 * waypoint parts, in travel order.
 *
 * `legs` is `meta[i].legs` from the API — one entry per stretch between consecutive
 * required stops, with inclusive `startIndex`/`endIndex` into `path`. Adjacent legs
 * *share* their boundary node (the required stop), so a naive slice per leg would
 * draw every waypoint twice. Instead each waypoint is lifted out into a part of its
 * own and the segments around it stop one node short, so every stop on the route is
 * rendered exactly once.
 *
 * With no required stops (`legs` absent, or a single leg) this is one segment
 * holding the whole filtered path — the rendering the results have always had.
 *
 * Note `path` may repeat a place name where the route drives back out of a stop it
 * had to turn into, so parts are cut by index and never by name.
 */
export function visibleSegments(path, legs, hiddenTypes) {
  if (!legs || legs.length < 2) {
    return [
      {
        kind: "segment",
        index: 0,
        leg: legs?.[0] ?? null,
        stops: visiblePath(path, hiddenTypes),
      },
    ];
  }
  const parts = [];
  legs.forEach((leg, j) => {
    const first = leg.startIndex + (j > 0 ? 1 : 0);
    const last = leg.endIndex - (j < legs.length - 1 ? 1 : 0);
    const slice = first <= last ? path.slice(first, last + 1) : [];
    parts.push({
      kind: "segment",
      index: j,
      leg,
      stops: visiblePath(slice, hiddenTypes),
    });
    if (j < legs.length - 1) {
      parts.push({ kind: "waypoint", index: j, place: path[leg.endIndex] });
    }
  });
  return parts;
}

/** The parts flattened back into one stop list, in travel order — what gets copied. */
export function shownStops(parts) {
  return parts.flatMap((part) =>
    part.kind === "segment" ? part.stops : [part.place],
  );
}

/**
 * A result chain drawn as the trip it is: one <RouteChain> per segment, with each
 * required stop between them raised onto a band of its own.
 *
 * The split is the point. A required stop is a place the driver actually stops at,
 * and the router now plans each stretch between stops as its own route — which is
 * why a result may drive back out of a junction it turned into. Drawn as one long
 * chain that reads as a mistake; drawn as "מקטע 1 ends here, מקטע 2 starts here" it
 * reads as what it is.
 *
 * props:
 *   parts             from visibleSegments()
 *   highlightedStops  passed straight through to each RouteChain
 *   renderHeader      optional (leg, index) => node, appended to a segment's header.
 *                     PathResults uses it for the per-segment match/priority/artery
 *                     chips, which stay inside its editor-only gate — the segment
 *                     name and endpoints below are always shown.
 */
export default function SegmentedRouteChain({
  parts,
  highlightedStops,
  renderHeader,
}) {
  // No required stops: exactly the chain the results have always rendered, with no
  // wrapper, no heading and no seam.
  if (parts.length === 1) {
    return (
      <RouteChain stops={parts[0].stops} highlightedStops={highlightedStops} />
    );
  }

  const lastSegment = parts.filter((p) => p.kind === "segment").length - 1;

  return (
    <div className="route-legs">
      {parts.map((part) =>
        part.kind === "waypoint" ? (
          <div className="route-waypoint" key={`w${part.index}`}>
            <span className="route-waypoint-stop">
              <IconPin size={13} aria-hidden="true" />
              {part.place}
            </span>
          </div>
        ) : (
          <section className="route-leg" key={`s${part.index}`}>
            <header className="route-leg-head">
              <span className="route-leg-name">מקטע {part.index + 1}</span>
              {part.leg && (
                <span className="route-leg-ends">
                  {part.leg.start}
                  <IconChevron size={13} aria-hidden="true" />
                  {part.leg.end}
                </span>
              )}
              {renderHeader?.(part.leg, part.index)}
            </header>
            {part.stops.length > 0 && (
              <RouteChain
                stops={part.stops}
                highlightedStops={highlightedStops}
                // Only the trip's real ends get the endpoint accent; a segment's
                // inner terminal is a mid-route stop sitting next to the waypoint
                // band, and accenting it would claim the trip starts or ends there.
                endpoints={
                  part.index === 0
                    ? "start"
                    : part.index === lastSegment
                      ? "end"
                      : "none"
                }
              />
            )}
          </section>
        ),
      )}
    </div>
  );
}
