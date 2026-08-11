import { useEffect, useRef, useState } from "react";

/**
 * Scroll-reveal for the home story: `shown` flips true the first time the
 * element is meaningfully on screen, and stays true.
 *
 * One-way on purpose — a section that replays its animation every time it
 * scrolls back into view turns a page into a fidget toy. Each section plays
 * once, the way a product page does.
 */
export function useReveal({ threshold = 0.3, eager = false } = {}) {
  const ref = useRef(null);
  // `eager`: the section straddling the fold on arrival. It is on screen from
  // the first frame, so it must never wait for a scroll to render.
  const [shown, setShown] = useState(eager);

  useEffect(() => {
    const el = ref.current;
    if (!el || shown) return;
    // No observer (or a browser that never fires one) must never leave the page
    // blank: fall back to "already revealed".
    if (typeof IntersectionObserver === "undefined") {
      setShown(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setShown(true);
          io.disconnect();
        }
      },
      // Bottom inset: a section counts as arrived once it is properly inside
      // the viewport, not the instant its first pixel crosses the edge.
      { threshold, rootMargin: "0px 0px -12% 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [threshold, shown]);

  return [ref, shown];
}
