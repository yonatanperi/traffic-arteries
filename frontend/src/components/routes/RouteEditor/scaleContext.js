import { createContext } from "react";

// The branched map's live zoom scale, shared as a *ref* (stable identity) so
// EditableRouteChain's drag modifier can read it without re-rendering the whole
// tree on every zoom frame. dnd-kit reports a reorder drag's delta in screen
// pixels, but the pill lives inside the scaled canvas, so a raw translate paints
// at `delta * scale` — drifting from the cursor whenever zoom ≠ 1. Dividing the
// translate by this scale keeps the drag 1:1. Default `{ current: 1 }` means every
// other use of EditableRouteChain (flat routes, results) is unaffected.
export const ScaleRefContext = createContext({ current: 1 });
