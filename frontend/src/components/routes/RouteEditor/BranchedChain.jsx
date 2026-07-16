import { useState } from "react";
import { EditableRouteChain } from "../../shared/RouteChain";
import IconButton from "../../ui/IconButton";
import { IconClose, IconAlert } from "../../ui/icons";
import {
  branchAt,
  removeBranch,
  patchNodePlaces,
  expandRoute,
} from "../../../utils/branches.js";
import "./BranchedChain.css";

/**
 * The editable converging tree for one route. A route is a shared **tail** with
 * **heads** that merge into the start of it; there is no primary head. It renders
 * right-to-left (RTL): origin heads on the upstream (right) side, converging
 * through elbow connectors into the tail that flows left toward the destination.
 * Every branch — and the tail — is embraced by a "[" bracket so it reads as a unit.
 *
 * To keep even a bushy route readable, exactly **one** head is extended at a time:
 * the focused head is shown in full (its whole subtree, all sub-branches), while
 * every other head collapses to a compact `origin ⋯ approach` chip you click to
 * focus (which folds the previously focused one). The focus is a single index into
 * the root's heads, clamped as the tree changes; a freshly-branched head is
 * auto-focused for filling.
 *
 * Every segment is an <EditableRouteChain>; its "+" offers "add stop" or "branch"
 * (split at that gap into converging heads). Emits the whole next route object,
 * so the route's priority rides along untouched.
 *
 * props:
 *   route     { places, priority, branches? } — the whole tree
 *   onChange  (nextRoute) => void
 *   suggestions / highlight / onRenameStop / compromisedPlaces — passed to every chain.
 */
export default function BranchedChain({
  route,
  onChange,
  suggestions,
  highlight,
  onRenameStop,
  compromisedPlaces,
}) {
  const [focused, setFocused] = useState(0);
  const ctx = {
    route,
    onChange,
    suggestions,
    highlight,
    onRenameStop,
    compromisedPlaces,
    focused,
    setFocused,
  };
  return (
    <div className="branched-scroll">
      <div className="branched">
        <TreeNode ctx={ctx} node={route} path={[]} collapsible bracket />
      </div>
    </div>
  );
}

/**
 * One node: its own segment chain (bracketed), and — if it has heads — the
 * converging subtree. `collapsible` (only the root) folds all but the focused head;
 * deeper down every head is shown in full.
 */
function TreeNode({ ctx, node, path, collapsible = false, bracket = false }) {
  const heads = node.branches ?? [];
  const junction = heads.length > 0;

  const chain = (
    <EditableRouteChain
      stops={node.places}
      onChange={(places) =>
        ctx.onChange(patchNodePlaces(ctx.route, path, places))
      }
      onAddBranch={(splitIndex) => {
        ctx.onChange(branchAt(ctx.route, path, splitIndex));
        // Adding at the root focuses the fresh head so it can be filled (a split
        // makes it index 1; an append puts it last). Deeper adds show in full
        // already, so the root focus is left alone.
        if (path.length === 0) {
          ctx.setFocused(splitIndex <= 0 ? heads.length : 1);
        }
      }}
      isJunction={junction}
      suggestions={ctx.suggestions}
      highlight={ctx.highlight}
      onRenameStop={ctx.onRenameStop}
      compromisedPlaces={ctx.compromisedPlaces}
    />
  );

  // A head is already embraced by its <li>'s bracket; only bracket the node's own
  // chain when asked (the root — so the tail / a plain route gets a "[" too).
  const bracketed = (
    <>
      {bracket && <span className="tnode-bracket" aria-hidden="true" />}
      {chain}
    </>
  );

  if (!junction) return <div className="tnode-leaf">{bracketed}</div>;

  const focusedIdx = collapsible ? Math.min(ctx.focused, heads.length - 1) : -1;

  return (
    <div className="tnode">
      <ul className="tnode-heads">
        {heads.map((head, i) => {
          const headPath = [...path, i];
          // Not collapsible (deeper than root) → every head is shown in full.
          const expanded = !collapsible || i === focusedIdx;
          return (
            <li className="tnode-head" key={i}>
              <IconButton
                size="sm"
                danger
                className="tnode-remove"
                ariaLabel="מחק ראש"
                title="מחק ראש"
                onClick={() => {
                  ctx.onChange(removeBranch(ctx.route, headPath));
                  if (path.length === 0) ctx.setFocused(0);
                }}
              >
                <IconClose size={13} />
              </IconButton>
              <span className="tnode-bracket" aria-hidden="true" />
              <div className="tnode-head-body">
                {expanded ? (
                  <>
                    <TreeNode ctx={ctx} node={head} path={headPath} />
                    {head.places.length === 0 && (
                      <span className="tnode-warn">
                        <IconAlert size={12} /> דרושה תחנה אחת לפחות
                      </span>
                    )}
                  </>
                ) : (
                  <CollapsedHead
                    head={head}
                    onExpand={() => ctx.setFocused(i)}
                  />
                )}
              </div>
            </li>
          );
        })}
      </ul>
      <div className="tnode-trunk">{bracketed}</div>
    </div>
  );
}

/** A folded-away head: `origin ⋯ approach` (+ an origins count if it forks); the
 *  whole thing is the "expand" control. */
function CollapsedHead({ head, onExpand }) {
  const leaves = expandRoute(head);
  const origin = leaves[0]?.[0] ?? "—";
  const approach = head.places[head.places.length - 1] ?? origin;
  const origins = leaves.length;
  return (
    <button
      type="button"
      className="tnode-collapsed"
      onClick={onExpand}
      title="הרחב ענף"
    >
      <span className="stop stop--start">{origin}</span>
      <span className="tnode-dots" aria-hidden="true">
        ⋯
      </span>
      {approach !== origin && (
        <span className="stop stop--end">{approach}</span>
      )}
      {origins > 1 && <span className="tnode-count">{origins} מקורות</span>}
    </button>
  );
}
