import { InlineStatus } from "@/features/strategies/InlineStatus";
import type { InlineStatusTone } from "@/features/strategies/InlineStatus";
import { cn } from "@/shared/lib/cn";

interface StatusButtonProps {
  /** Every text the button can show, already translated and all different. The button is as wide as the longest. */
  texts: readonly string[];
  /** The one of `texts` shown now. The others stay in the layout, hidden from sight and from assistive technology. */
  shown: string;
  /** What the status region says after the button; `null` while there is nothing to say. */
  message: string | null;
  tone?: InlineStatusTone;
  onClick: () => void;
  disabled?: boolean;
  className: string;
}

/**
 * A button whose own text tells the news ("Saved", "Copied"), with the status region that tells a screen
 * reader, because a change of a button's text is not announced. All the texts sit in ONE grid cell, so the
 * button has the width of its longest and changing the text moves nothing around it. Only the shown text is
 * seen or read, which makes it the button's accessible name.
 */
export function StatusButton({ texts, shown, message, tone = "neutral", onClick, disabled, className }: StatusButtonProps) {
  return (
    <>
      <button type="button" onClick={onClick} disabled={disabled} className={className}>
        <span className="inline-grid justify-items-center">
          {texts.map((text) => (
            <span
              key={text}
              aria-hidden={text === shown ? undefined : true}
              className={cn("col-start-1 row-start-1", text !== shown && "invisible")}
            >
              {text}
            </span>
          ))}
        </span>
      </button>
      <InlineStatus message={message} tone={tone} />
    </>
  );
}
