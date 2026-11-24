import { useTranslation } from "react-i18next";

import type { KeyMarkSpec } from "@/shared/credentials/key-state";
import { cn } from "@/shared/lib/cn";

export interface KeyMarkProps {
  mark: KeyMarkSpec;
  /** The element drawn; a tag inside a list is an `li`. */
  as?: "span" | "li" | "p";
  className?: string | undefined;
}

const TAG = "whitespace-nowrap rounded border px-2 py-0.5 font-mono text-xs";

/**
 * The word of a state's mark: `read-only` or `no key`. It is a word, never colour
 * alone; the colour only says whether the owner has something to do. Amber is the
 * state that needs an action (a key that cannot trade, a keyless exchange with a
 * pool on); grey is information. It is drawn as a tag with a solid border, which
 * the dashed tags of the owner's confirmations are not, on the key's card.
 */
export function KeyMark({ mark, as: Element = "span", className }: KeyMarkProps) {
  const { t } = useTranslation();
  const amber = mark.tone === "amber";
  const look = cn(TAG, amber ? "border-decision text-decision" : "border-rule-strong text-ink-3");
  return <Element className={cn(look, className)}>{t(`scope.mark.${mark.word}`)}</Element>;
}
