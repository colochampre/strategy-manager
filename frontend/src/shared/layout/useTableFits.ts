import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { RefObject } from "react";

/**
 * Whether the table rendered inside `ref` fits its box, for a view that has a narrower way to say the same thing
 * (cards) and renders ONE of the two. The window's width cannot tell: the same window holds a wide column with the
 * sidebar folded and a narrow one beside an aside (L45).
 *
 * The table is drawn first. When it is wider than its box, the width it needed is kept and the view turns to its
 * narrow form, before the paint; when the wrapper is wide enough for that width again, the table comes back. A
 * browser without `ResizeObserver` (and jsdom, which lays nothing out) reads as fitting.
 */
export function useTableFits(): { ref: RefObject<HTMLDivElement | null>; fits: boolean } {
  const ref = useRef<HTMLDivElement | null>(null);
  const [needed, setNeeded] = useState<number | null>(null);
  const [width, setWidth] = useState<number | null>(null);
  const fits = needed === null || width === null || width >= needed;

  useLayoutEffect(() => {
    const wrapper = ref.current;
    if (wrapper === null) return undefined;
    // On mount nothing is stored unless the table spills, so a view that fits renders once, as before (L45).
    const check = (resized: boolean) => {
      const table = wrapper.querySelector("table");
      const box = table?.parentElement;
      if (table && box && table.scrollWidth > box.clientWidth) {
        // The table's own width plus the box's borders: what the wrapper must hold for it to fit.
        setNeeded(table.scrollWidth + (box.offsetWidth - box.clientWidth));
        setWidth(wrapper.clientWidth);
      } else if (resized) {
        setWidth(wrapper.clientWidth);
      }
    };
    check(false);
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(() => check(true));
    observer.observe(wrapper);
    const table = wrapper.querySelector("table");
    if (table !== null) observer.observe(table);
    return () => observer.disconnect();
  }, [fits]);

  // The panel's faces are web fonts. A table first drawn in the fallback face can spill by a few pixels and keep
  // its narrow form for good, since nothing measures it again (seen on the Users page in production, RD.8). Once
  // the fonts load, the stored width is dropped, so the table is drawn and measured again in the real face, still
  // before the paint.
  useEffect(() => {
    const fonts = typeof document === "undefined" ? undefined : document.fonts;
    if (fonts === undefined) return undefined;
    let live = true;
    const retry = () => {
      if (live) setNeeded(null);
    };
    fonts.addEventListener("loadingdone", retry);
    if (fonts.status === "loading") void fonts.ready.then(retry);
    return () => {
      live = false;
      fonts.removeEventListener("loadingdone", retry);
    };
  }, []);

  return { ref, fits };
}
