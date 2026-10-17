import { useEffect, useRef, useState } from "react";

/** Width of an element in CSS pixels, kept up to date (ResizeObserver). Charts use it to draw at 1:1
 *  scale, so text keeps its size when a column is resized. */
export function useWidth<T extends Element>(fallback: number) {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => {
      const w = Math.round(e.contentRect.width);
      if (w > 0) setWidth((old) => (Math.abs(old - w) >= 1 ? w : old));
    });
    ro.observe(el);
    return () => ro.disconnect();
  });
  return [ref, width] as const;
}
