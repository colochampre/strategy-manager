import { useTranslation } from "react-i18next";

import type { KeyMarkSpec } from "@/shared/credentials/key-state";
import { cn } from "@/shared/lib/cn";
import { PILL, PillDot } from "@/shared/ui/Pill";

export interface KeyMarkProps {
  mark: KeyMarkSpec;
  /** The element drawn; a tag inside a list is an `li`. */
  as?: "span" | "li" | "p";
  /** `tag` (the default) is the mark on a facts list; `pill` is the state cell of a keys' row (ex6). */
  variant?: "tag" | "pill";
  className?: string | undefined;
}

const TAG = "whitespace-nowrap rounded border px-2 py-0.5 font-mono text-xs";

/**
 * The word of a state's mark: `read-only` or `no key`. It is a word, never colour
 * alone; the colour only says whether the owner has something to do. Amber is the
 * state that needs an action (a key that cannot trade, a keyless exchange with a
 * pool on); grey is information. It is drawn as a tag with a solid border, which
 * the dashed tags of the owner's confirmations are not, or as the state pill of a row.
 */
export function KeyMark({ mark, as: Element = "span", variant = "tag", className }: KeyMarkProps) {
  const { t } = useTranslation();
  const amber = mark.tone === "amber";
  if (variant === "pill") {
    return (
      <Element
        className={cn(
          PILL,
          amber ? "border-decision/40 bg-decision/14 text-decision" : "border-ink-2/40 bg-ink-2/11 text-ink-2",
          className,
        )}
      >
        <PillDot className={amber ? "bg-decision" : "bg-ink-2"} />
        {t(`scope.mark.${mark.word}`)}
      </Element>
    );
  }
  const look = cn(TAG, amber ? "border-decision text-decision" : "border-rule-strong text-ink-3");
  return <Element className={cn(look, className)}>{t(`scope.mark.${mark.word}`)}</Element>;
}
