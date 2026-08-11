import { useEffect, useState } from "react";

const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * A number that rolls up from zero once its section is revealed (`run`).
 *
 * rAF rather than a CSS counter animation because the value comes from the
 * places list at runtime, and because the roll has to ease out — a linear
 * count reads like a loading spinner, an eased one reads like a result
 * settling.
 */
export default function CountUp({ value, run, duration = 1200 }) {
  const [shown, setShown] = useState(0);

  useEffect(() => {
    if (!run) return;
    if (prefersReducedMotion() || value <= 0) {
      setShown(value);
      return;
    }
    let raf;
    let start;
    function step(t) {
      if (start === undefined) start = t;
      const p = Math.min(1, (t - start) / duration);
      setShown(Math.round(value * (1 - Math.pow(1 - p, 3)))); // ease-out cubic
      if (p < 1) raf = requestAnimationFrame(step);
    }
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [run, value, duration]);

  return <>{shown}</>;
}
