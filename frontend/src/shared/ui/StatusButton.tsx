import { Check, LoaderCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { IconButton } from "@/shared/ui/IconButton";
import type { IconButtonTone } from "@/shared/ui/IconButton";
import { InlineStatus } from "@/shared/ui/InlineStatus";
import type { InlineStatusTone } from "@/shared/ui/InlineStatus";
import { cn } from "@/shared/lib/cn";

interface StatusButtonProps {
  /** Every text the button can show, already translated and all different. The button is as wide as the longest. */
  texts: readonly string[];
  /** The one of `texts` shown now. The others stay in the layout, hidden from sight and from assistive technology. */
  shown: string;
  /** What the status region says after the button; `null` while there is nothing to say. */
  message: string | null;
  tone?: InlineStatusTone;
  onClick?: () => void;
  /** The button submits its form (so Enter in a field presses it) instead of being a plain button. */
  submit?: boolean;
  disabled?: boolean;
  className?: string;
  /** Drawn left of the texts, outside their grid cell, so it stays while the text changes. */
  icon?: LucideIcon;
  /**
   * Only the icon is drawn. The shown text becomes the accessible name and the tooltip, so a screen reader hears
   * what the text said; the icon follows the state: `icon` at rest, a spinner while `busy`, a check once the
   * shown text is no longer the first of `texts`. `className` is not used: `look` picks the style.
   */
  iconOnly?: boolean;
  /** A request is in flight (icon only: the spinner). */
  busy?: boolean;
  /** The look of an icon-only button. */
  look?: IconButtonTone;
}

/**
 * A button whose own text tells the news ("Saved", "Copied"), with the status region that tells a screen
 * reader, because a change of a button's text is not announced. All the texts sit in ONE grid cell, so the
 * button has the width of its longest and changing the text moves nothing around it. Only the shown text is
 * seen or read, which makes it the button's accessible name.
 */
export function StatusButton({
  texts,
  shown,
  message,
  tone = "neutral",
  onClick,
  submit = false,
  disabled,
  className,
  icon: Icon,
  iconOnly = false,
  busy = false,
  look = "neutral",
}: StatusButtonProps) {
  if (iconOnly && Icon !== undefined) {
    const done = !busy && shown !== texts[0];
    return (
      <>
        <IconButton
          label={shown}
          icon={busy ? LoaderCircle : done ? Check : Icon}
          spin={busy}
          onClick={onClick}
          submit={submit}
          disabled={disabled}
          tone={look}
        />
        <InlineStatus message={message} tone={tone} />
      </>
    );
  }
  return (
    <>
      <button
        type={submit ? "submit" : "button"}
        onClick={onClick}
        disabled={disabled}
        className={Icon === undefined ? className : cn(className, "inline-flex items-center gap-1.5")}
      >
        {Icon !== undefined && <Icon aria-hidden="true" className="size-4 shrink-0" />}
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
