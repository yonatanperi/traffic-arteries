import Select from "../../ui/Select";
import {
  PRIORITY_OPTIONS,
  isDowngraded,
  priorityLetter,
} from "../../../utils/priorities.js";
import "./PrioritySelect.css";

/**
 * The priority picker, in the two places a priority is stated: a plain route's card
 * header, and each head of a branched one (where there is no route-level priority —
 * a head rates the corridor it generates, and only that one).
 *
 * One control for both, because they are the same decision at two scopes; the only
 * difference is how much room there is to say it.
 *
 * props:
 *   value      0..3 — always a concrete priority, never "unset"
 *   onChange   (0..3) => void
 *   compact    dot + letter only (the head chip), instead of the full label
 */
export default function PrioritySelect({
  value,
  onChange,
  compact = false,
  className,
  ...rest
}) {
  return (
    <Select
      size={compact ? "sm" : "md"}
      value={value}
      onChange={onChange}
      options={PRIORITY_OPTIONS}
      renderOption={renderPriorityOption}
      renderValue={compact ? renderCompactValue : renderPriorityOption}
      className={
        "priority-sel" +
        (compact ? " priority-sel--compact" : "") +
        // Downgraded is what's worth colouring: it's the state that costs the
        // route something.
        (isDowngraded(value) ? " priority-sel--downgraded" : "") +
        (className ? " " + className : "")
      }
      {...rest}
    />
  );
}

/**
 * A priority option: a dot shaded by how far the priority is from the best, then
 * the label. The ramp is what a bare letter can't convey — that these four values
 * are ordered, and that picking a later one costs the route something.
 */
function renderPriorityOption(option) {
  return (
    <>
      <PriorityDot priority={option.priority} />
      {option.label}
    </>
  );
}

/** The closed state of a head's chip: the dot and the bare letter, nothing else —
 *  it sits inside the tree, where a full "עדיפות ב׳" would crowd the branch. */
function renderCompactValue(option) {
  return (
    <>
      <PriorityDot priority={option.priority} />
      {priorityLetter(option.priority)}
    </>
  );
}

/** The priority ramp as a single dot — also the badge the card header lists a
 *  branched route's spread of priorities with. */
export function PriorityDot({ priority }) {
  return (
    <span
      className="priority-dot"
      style={{ "--priority-step": priority }}
      aria-hidden="true"
    />
  );
}
