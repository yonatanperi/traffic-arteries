import { useSearchParams } from "react-router-dom";

/**
 * Read access to the URL's search params. Returns a single `getParam`
 * function that covers both a scalar param (?key=value) and a repeated one
 * (?key=a&key=b) — pass `{ list: true }` to read every value for a key
 * instead of just the first.
 */
export function useGetUrlParams() {
  const [searchParams] = useSearchParams();

  function getParam(key, { list = false, defaultValue = list ? [] : "" } = {}) {
    if (list) return searchParams.getAll(key);
    return searchParams.get(key) ?? defaultValue;
  }

  return { getParam };
}

/**
 * Write access to the URL's search params. Returns a single `setParams`
 * function taking a `{ key: value }` dict — only the given keys change,
 * every other param is left as-is. A value of `null` removes that param; an
 * array value sets it as a repeated param (?key=a&key=b), replacing every
 * existing value for that key; anything else is set as a single scalar
 * value (an empty string also removes the param, same as `null`). Every
 * write replaces the current history entry ({ replace: true }) instead of
 * pushing a new one, so typing into a field doesn't spam the back button
 * with a step per keystroke.
 */
export function useSetUrlParams() {
  const [, setSearchParams] = useSearchParams();

  function setParams(values) {
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(values)) {
          params.delete(key);
          if (value == null || value === "") continue;
          if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
          else params.set(key, value);
        }
        return params;
      },
      { replace: true },
    );
  }

  return { setParams };
}

/**
 * Removes one or more search params entirely. Returns a single
 * `removeParams` function taking an array of keys.
 */
export function useRemoveUrlParams() {
  const [, setSearchParams] = useSearchParams();

  function removeParams(keys) {
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        keys.forEach((key) => params.delete(key));
        return params;
      },
      { replace: true },
    );
  }

  return { removeParams };
}
