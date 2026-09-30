import { useEffect, useState } from "react";

/**
 * Tracks the content width of an element, in CSS pixels, with a `ResizeObserver`.
 *
 * Returns a callback ref for the element and the width to draw at: `fallback`
 * until the first measurement, and whenever the platform has no `ResizeObserver`
 * (jsdom). An empty measurement (a hidden box reports 0) is ignored, so the last
 * good width stays instead of collapsing the drawing.
 */
export function useElementWidth<T extends Element>(fallback: number): [(node: T | null) => void, number] {
  const [node, setNode] = useState<T | null>(null);
  const [width, setWidth] = useState<number | null>(null);

  useEffect(() => {
    if (node === null || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[entries.length - 1];
      if (entry === undefined) return;
      const measured = Math.round(entry.contentRect.width);
      if (measured > 0) setWidth(measured);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [node]);

  return [setNode, width ?? fallback];
}
