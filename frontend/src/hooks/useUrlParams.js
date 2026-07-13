import { useSearchParams } from "react-router-dom";

/**
 * A single URL search-param, mirrored as a useState-shaped [value, setValue]
 * pair. Every write replaces the current history entry ({ replace: true })
 * instead of pushing a new one, so typing into a field doesn't spam the back
 * button with a step per keystroke.
 */
export function useUrlParam(key, defaultValue = "") {
  const [searchParams, setSearchParams] = useSearchParams();
  const value = searchParams.get(key) ?? defaultValue;

  function setValue(next) {
    setSearchParams(
      (prev) => {
        const current = prev.get(key) ?? defaultValue;
        const resolved = typeof next === "function" ? next(current) : next;
        const params = new URLSearchParams(prev);
        if (resolved) params.set(key, resolved);
        else params.delete(key);
        return params;
      },
      { replace: true },
    );
  }

  return [value, setValue];
}

/**
 * A repeated URL search-param (?key=a&key=b), mirrored as a plain string
 * array via getAll/append. Repeated keys (rather than a joined/delimited
 * single value) sidestep any escaping concerns with place names.
 */
export function useUrlListParam(key) {
  const [searchParams, setSearchParams] = useSearchParams();
  const values = searchParams.getAll(key);

  function setValues(next) {
    setSearchParams(
      (prev) => {
        const current = prev.getAll(key);
        const resolved = typeof next === "function" ? next(current) : next;
        const params = new URLSearchParams(prev);
        params.delete(key);
        resolved.forEach((v) => params.append(key, v));
        return params;
      },
      { replace: true },
    );
  }

  return [values, setValues];
}
