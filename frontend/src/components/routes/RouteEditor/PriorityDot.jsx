import { PRIORITY_OPTIONS } from "../../../utils/priorities.js";
import "./PriorityDot.css";

/**
 * The priority ramp as a single dot — the one shared glyph everything that shows a
 * priority is built from: the popover's options, a mark's tag on the chain, the
 * card header's spread badge, and the toolbar's filter list.
 *
 * There is no priority *picker* component any more: a priority is stated by marking
 * a range of stops, so the only place to choose one is <PriorityMarkPopover>, which
 * opens over the range that was just swept.
 */
export function PriorityDot({ priority }) {
  return (
    <span
      className="priority-dot"
      style={{ "--priority-step": priority }}
      aria-hidden="true"
    />
  );
}

/**
 * A priority option: the dot, then the label. The ramp is what a bare letter can't
 * convey — that these four values are ordered, and that picking a later one costs
 * the route something.
 */
export function PriorityOption({ option }) {
  return (
    <>
      <PriorityDot priority={option.priority} />
      {option.label}
    </>
  );
}

export { PRIORITY_OPTIONS };
