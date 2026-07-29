import { useRef, useState } from "react";

// Each history entry is a full copy of the collection (the server hands back a
// fresh object on every save, so nothing is shared between entries). Bound the
// depth rather than letting a long editing session grow without limit.
const HISTORY_LIMIT = 50;

/**
 * Holds a JSON-serializable value and persists it through `saveFn` on every
 * `apply(next)` call — but only once `next` passes `isValid`, and only if it
 * actually differs from what's already persisted. Saves are chained onto a
 * promise ref so concurrent edits never race each other out of order.
 *
 * `seed(initial)` sets the starting value once the real data has loaded
 * (e.g. after an async fetch) without triggering a save.
 *
 * Every `apply` also records the previous value, so `undo`/`redo` can walk back
 * and forth through the session's edits. They re-enter the same save path, so an
 * undo persists exactly like the edit it reverts. Note that one *user* action is
 * not always one entry: renaming a stop everywhere emits the single-spot edit and
 * then the rename-all map (see RouteEditor.confirmRename), so it takes two undos.
 */
export function useAutoSave(saveFn, isValid) {
  const [value, setValue] = useState(null);
  const originalRef = useRef(null);
  const savingRef = useRef(Promise.resolve());
  // `value` as of right now, readable from an event handler that has already
  // called `commit` this tick (state wouldn't have caught up yet).
  const valueRef = useRef(null);

  // The two stacks live in refs, not state: holding Ctrl+Z repeats the keydown
  // faster than React re-renders, and a second handler reading last render's
  // stack would undo the same entry twice. `bump` exists only to re-render so
  // the buttons' enabled state follows.
  const pastRef = useRef([]); // older values, oldest -> newest
  const futureRef = useRef([]); // undone values, newest first
  const [, bump] = useState(0);

  function setHistory(past, future) {
    pastRef.current = past;
    futureRef.current = future;
    bump((n) => n + 1);
  }

  function seed(initial) {
    setValue(initial);
    valueRef.current = initial;
    originalRef.current = JSON.stringify(initial);
    setHistory([], []);
  }

  // Sets + persists, without touching the history — the shared path for a fresh
  // edit and for an undo/redo alike.
  function commit(next) {
    setValue(next);
    valueRef.current = next;

    const snapshot = JSON.stringify(next);
    if (snapshot === originalRef.current) return; // no net change vs. what's persisted
    if (!isValid(next)) return; // wait until valid

    savingRef.current = savingRef.current
      .catch(() => {})
      .then(async () => {
        const saved = await saveFn(next);
        originalRef.current = snapshot;
        // Adopt the server's normalized copy, unless a later edit already moved
        // us on. Assigning ref and state together keeps them from drifting.
        if (JSON.stringify(valueRef.current) === snapshot) {
          valueRef.current = saved;
          setValue(saved);
        }
      });
  }

  function apply(next) {
    const prev = valueRef.current;
    if (prev !== null && JSON.stringify(prev) !== JSON.stringify(next)) {
      // A new edit forks the timeline: nothing left to redo.
      setHistory([...pastRef.current, prev].slice(-HISTORY_LIMIT), []);
    }
    commit(next);
  }

  function undo() {
    const past = pastRef.current;
    if (!past.length) return;
    setHistory(past.slice(0, -1), [valueRef.current, ...futureRef.current]);
    commit(past[past.length - 1]);
  }

  function redo() {
    const future = futureRef.current;
    if (!future.length) return;
    setHistory(
      [...pastRef.current, valueRef.current].slice(-HISTORY_LIMIT),
      future.slice(1),
    );
    commit(future[0]);
  }

  return {
    value,
    seed,
    apply,
    undo,
    redo,
    canUndo: pastRef.current.length > 0,
    canRedo: futureRef.current.length > 0,
  };
}
