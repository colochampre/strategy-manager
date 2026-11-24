import { cn } from "@/shared/lib/cn";

/** The favicon set's own image, served from the bundle root (`frontend/public/`). */
export const BRAND_ICON_SRC = "/android-chrome-192x192.png";

/**
 * The app's icon beside its name: the same image as the favicon (owner, 2026-11-24). Decorative, so `alt` is empty
 * and the name next to it is what assistive technology reads.
 */
export function BrandIcon({ className }: { className?: string }) {
  return <img src={BRAND_ICON_SRC} alt="" width={32} height={32} className={cn("size-8 shrink-0", className)} />;
}
