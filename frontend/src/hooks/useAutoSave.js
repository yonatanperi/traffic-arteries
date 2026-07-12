import { useRef, useState } from "react";

/**
 * Holds a JSON-serializable value and persists it through `saveFn` on every
 * `apply(next)` call — but only once `next` passes `isValid`, and only if it
 * actually differs from what's already persisted. Saves are chained onto a
 * promise ref so concurrent edits never race each other out of order.
 *
 * `seed(initial)` sets the starting value once the real data has loaded
 * (e.g. after an async fetch) without triggering a save.
 */
export function useAutoSave(saveFn, isValid) {
  const [value, setValue] = useState(null);
  const originalRef = useRef(null);
  const savingRef = useRef(Promise.resolve());

  function seed(initial) {
    setValue(initial);
    originalRef.current = JSON.stringify(initial);
  }

  function apply(next) {
    setValue(next);

    const snapshot = JSON.stringify(next);
    if (snapshot === originalRef.current) return; // no net change vs. what's persisted
    if (!isValid(next)) return; // wait until valid

    savingRef.current = savingRef.current
      .catch(() => {})
      .then(async () => {
        const saved = await saveFn(next);
        originalRef.current = snapshot;
        setValue((cur) => (JSON.stringify(cur) === snapshot ? saved : cur));
      });
  }

  return { value, seed, apply };
}
