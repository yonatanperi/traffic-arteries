import { useCallback, useEffect, useRef, useState } from "react";
import { TransformWrapper, TransformComponent } from "react-zoom-pan-pinch";
import { EditableRouteChain } from "../../shared/RouteChain";
import IconButton from "../../ui/IconButton";
import {
  IconClose,
  IconAlert,
  IconPlus,
  IconMinus,
  IconFit,
} from "../../ui/icons";
import PrioritySelect from "./PrioritySelect";
import {
  branchAt,
  removeBranch,
  patchNodePlaces,
  effectivePriority,
  setNodePriority,
} from "../../../utils/branches.js";
import { ScaleRefContext } from "./scaleContext.js";
import "./BranchedChain.css";

// The interactive surface inside the tree — a pointer press here acts on the
// element instead of panning the map: the pills (`.stop`, click-to-edit and now
// drag-to-reorder — excluding them from the pan is what lets a pill drag reorder
// while an empty-canvas drag pans), every control (`button`, incl.
// `.insert-slot`/IconButtons), and the inline editors (`input`, `.stop-edit`,
// `.ac`). Panning happens on the empty canvas / connectors between them. Also fed
// to wheel/pinch so a gesture over an input doesn't zoom.
// (react-zoom-pan-pinch matches these against the event target.)
const PAN_EXCLUDED = [
  "input",
  "textarea",
  "button",
  "stop",
  "ac",
  "sel",
  "stop-edit",
];

// A low floor only so the first programmatic fit isn't clamped before the real
// minScale (the fit scale) is measured; after that minScale IS the fit scale.
const SCALE_FLOOR = 0.05;
const MAX_SCALE = 2;

/** The scale at which the whole (unscaled) tree just fits the viewport, both axes,
 *  never upscaling past 1. Returns null until the DOM is measurable. */
function measureFitScale(ref) {
  const wrapper = ref?.instance?.wrapperComponent;
  const content = ref?.instance?.contentComponent;
  if (!wrapper || !content) return null;
  const cw = content.offsetWidth;
  const ch = content.offsetHeight;
  if (!cw || !ch) return null;
  return Math.min(wrapper.offsetWidth / cw, wrapper.offsetHeight / ch, 1);
}

/**
 * The editable converging tree for one route. A route is a shared **tail** with
 * **heads** that merge into the start of it; there is no primary head. It renders
 * right-to-left (RTL): origin heads on the upstream (right) side, converging
 * through elbow connectors into the tail that flows left toward the destination.
 * Every branch — and the tail — is embraced by a "[" bracket so it reads as a unit.
 *
 * A **branched** route (one with heads) is shown on a **Figma-style map**: the whole
 * tree is always rendered in full inside a bounded viewport the user can pan (drag
 * the empty canvas), zoom (wheel / pinch / the control buttons), and fit/reset — so
 * a bushy tree never overflows the card. A **flat** route (no heads) is just its
 * inline chain, exactly as before — no viewport, no controls.
 *
 * Every segment is an <EditableRouteChain>; its "+" offers "add stop" or "branch"
 * (split at that gap into converging heads). Emits the whole next route object, so
 * the route's priority rides along untouched.
 *
 * Each head also carries its own <PrioritySelect> at its tip: a branched route has
 * no single priority — each head rates the corridor it generates (itself → down the
 * shared tail → the destination), and rating one leaves its siblings alone.
 *
 * props:
 *   route     { places, priority, branches? } — the whole tree
 *   onChange  (nextRoute) => void
 *   suggestions / highlight / onRenameStop / compromisedPlaces — passed to every chain.
 *   previewReversed  hover-preview only (non-branched routes): show the root chain's
 *                 stops in reverse order via its own drag-reorder animation, without
 *                 touching `route` — the reverse button is the only thing that sets it.
 */
export default function BranchedChain({
  route,
  onChange,
  suggestions,
  highlight,
  onRenameStop,
  compromisedPlaces,
  previewReversed = false,
}) {
  // A branched route lives on the pan/zoom map; a plain (branchless) route is the
  // bare inline chain. This split drives two things: the leading "[" bracket
  // (tree only) and the 6-per-row wrap (only the mapped tree wraps; a flat chain
  // wraps to fit the card as before). Stop drag-reorder is enabled either way —
  // inside the map a pill drag reorders (it's excluded from the canvas pan) and
  // stays 1:1 with the cursor at any zoom via the shared scale ref below.
  const branched = route.branches?.length > 0;

  const ctx = {
    route,
    onChange,
    suggestions,
    highlight,
    onRenameStop,
    compromisedPlaces,
    sortable: true,
    wrapEvery: branched ? 6 : null,
    // Only ever true for the root chain of a non-branched route (see prop doc).
    previewReversed,
  };

  // The most zoomed-OUT state is the whole tree fitting the viewport: minScale is
  // the measured fit scale, so you can't zoom out past the tree's boundary into
  // empty space. Starts at a low floor so the first fit isn't clamped before the
  // real value is measured (on init / resize).
  const [minScale, setMinScale] = useState(SCALE_FLOOR);
  const apiRef = useRef(null);
  // The live zoom, shared with every EditableRouteChain (via context) so a stop
  // reorder drag divides its screen-pixel delta by the scale and stays 1:1 with
  // the cursor. A ref (not state) so zoom frames don't re-render the whole tree.
  const scaleRef = useRef(1);

  const tree = (
    <ScaleRefContext.Provider value={scaleRef}>
      <div className="branched">
        <TreeNode ctx={ctx} node={route} path={[]} bracket={branched} />
      </div>
    </ScaleRefContext.Provider>
  );

  // Fit the tree to the viewport and pin minScale to that fit — centered. Called on
  // init, on the Fit button, and on resize (the fit scale depends on both sizes).
  const fitToView = useCallback((ref, animate = true) => {
    const api = ref ?? apiRef.current;
    if (!api) return;
    const scale = measureFitScale(api);
    if (scale == null) return;
    setMinScale(scale);
    scaleRef.current = scale;
    const wrapper = api.instance.wrapperComponent;
    const content = api.instance.contentComponent;
    const x = (wrapper.offsetWidth - content.offsetWidth * scale) / 2;
    const y = (wrapper.offsetHeight - content.offsetHeight * scale) / 2;
    api.setTransform(x, y, scale, animate ? 200 : 0, "easeOut");
  }, []);

  // Re-fit when the card/window resizes so the boundary stays the tree.
  useEffect(() => {
    const onResize = () => fitToView(apiRef.current, false);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [fitToView]);

  // A plain (branchless) route needs no map — render the inline chain as before.
  if (!branched) return tree;

  return (
    <TransformWrapper
      minScale={minScale}
      maxScale={MAX_SCALE}
      initialScale={minScale}
      // Bounded panning: you can't drag the tree off into empty space, and the zoom
      // buttons / fit stay anchored on the tree rather than flying to a corner.
      // `centerZoomedOut` keeps the tree centered when it's smaller than the viewport.
      limitToBounds
      centerZoomedOut
      doubleClick={{ disabled: true }}
      panning={{ excluded: PAN_EXCLUDED }}
      // Gentle, relaxed wheel/trackpad zoom (the default is jumpy).
      wheel={{ excluded: PAN_EXCLUDED, step: 0.04 }}
      pinch={{ excluded: PAN_EXCLUDED, step: 3 }}
      // Keep the shared scale ref live so a stop reorder drag stays 1:1 under zoom.
      onTransformed={(_ref, state) => {
        scaleRef.current = state.scale;
      }}
      onInit={(ref) => {
        apiRef.current = ref;
        fitToView(ref, false);
      }}
    >
      {(utils) => (
        <div className="branched-map">
          <div className="branched-map-controls">
            <IconButton
              size="md"
              ariaLabel="התאם לתצוגה"
              title="התאם לתצוגה"
              onClick={() => fitToView(utils)}
            >
              <IconFit size={16} />
            </IconButton>
            <IconButton
              size="md"
              ariaLabel="הגדל"
              title="הגדל"
              onClick={() => utils.zoomIn(0.2, 200, "easeOut")}
            >
              <IconPlus size={16} />
            </IconButton>
            <IconButton
              size="md"
              ariaLabel="הקטן"
              title="הקטן"
              onClick={() => utils.zoomOut(0.2, 200, "easeOut")}
            >
              <IconMinus size={16} />
            </IconButton>
          </div>
          <TransformComponent
            wrapperClass="branched-viewport"
            contentClass="branched-canvas"
          >
            {tree}
          </TransformComponent>
        </div>
      )}
    </TransformWrapper>
  );
}

/**
 * One node: its own segment chain (bracketed), and — if it has heads — the
 * converging subtree, with every head shown in full (recursively).
 */
function TreeNode({ ctx, node, path, bracket = false }) {
  const heads = node.branches ?? [];
  const junction = heads.length > 0;

  const chain = (
    <EditableRouteChain
      stops={node.places}
      onChange={(places) =>
        ctx.onChange(patchNodePlaces(ctx.route, path, places))
      }
      onAddBranch={(splitIndex) =>
        ctx.onChange(branchAt(ctx.route, path, splitIndex))
      }
      isJunction={junction}
      // Stops drag-reorder within their own segment, on the map too: a pill press
      // is excluded from the canvas pan, so it reorders (only empty-canvas drags
      // pan). The scale ref keeps that drag 1:1 with the cursor at any zoom.
      sortable={ctx.sortable}
      // On the mapped tree, break each segment to a new row every 6 stops rather
      // than running one long line the user must pan across.
      wrapEvery={ctx.wrapEvery}
      // Accent only the *real* tree edges: a real origin is a leaf segment's first
      // stop (a junction's first stop is where its sub-heads converge — internal),
      // and the one real destination is the root/tail's last stop (a head's last
      // stop just connects into its parent — internal).
      showStart={!junction}
      showEnd={path.length === 0}
      suggestions={ctx.suggestions}
      highlight={ctx.highlight}
      onRenameStop={ctx.onRenameStop}
      compromisedPlaces={ctx.compromisedPlaces}
      previewReversed={ctx.previewReversed}
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

  return (
    <div className="tnode">
      <ul className="tnode-heads">
        {heads.map((head, i) => {
          const headPath = [...path, i];
          return (
            <li className="tnode-head" key={i}>
              <div className="tnode-head-tools">
                <IconButton
                  size="sm"
                  danger
                  className="tnode-remove"
                  ariaLabel="מחק ראש"
                  title="מחק ראש"
                  onClick={() => ctx.onChange(removeBranch(ctx.route, headPath))}
                >
                  <IconClose size={13} />
                </IconButton>
                {/* The head's priority — it rates every corridor that runs from
                    here down the shared tail, and nothing else in the tree. Shown
                    as the priority the head *rides at*, which for a head that has
                    never been rated is the one it takes from the segment it
                    converges into; picking a value here always states it outright. */}
                <PrioritySelect
                  compact
                  value={effectivePriority(ctx.route, headPath)}
                  onChange={(priority) =>
                    ctx.onChange(setNodePriority(ctx.route, headPath, priority))
                  }
                  aria-label="עדיפות הראש"
                  title="עדיפות המסלול מראש זה ועד היעד. אינה משפיעה על ראשים אחרים."
                />
              </div>
              <span className="tnode-bracket" aria-hidden="true" />
              <div className="tnode-head-body">
                <TreeNode ctx={ctx} node={head} path={headPath} />
                {head.places.length === 0 && (
                  <span className="tnode-warn">
                    <IconAlert size={12} /> דרושה תחנה אחת לפחות
                  </span>
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
