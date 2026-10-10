import { type KeyboardEvent, type ReactNode, type RefObject, useId, useRef, useState } from "react";

import { cn } from "@/shared/lib/cn";

/** What the hook shares with the two parts: whether the text is open and the ids that tie them. */
export interface InfoDisclosureState {
  open: boolean;
  textId: string;
  buttonRef: RefObject<HTMLButtonElement | null>;
  toggle: () => void;
  /** Closes the text and puts focus back on the button, whichever element had it. */
  close: () => void;
}

/**
 * The state of one information button (design § B2): closed by default, local to the component that
 * calls it, never stored. Each call owns its own state, so two disclosures open and close independently.
 */
export function useInfoDisclosure(): InfoDisclosureState {
  const [open, setOpen] = useState(false);
  const textId = useId();
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  return {
    open,
    textId,
    buttonRef,
    toggle: () => setOpen(!open),
    close: () => {
      setOpen(false);
      buttonRef.current?.focus();
    },
  };
}

/** Escape closes an open text from the button or from inside the text; focus ends on the button. */
function closeOnEscape(disclosure: InfoDisclosureState) {
  return (event: KeyboardEvent) => {
    if (event.key === "Escape" && disclosure.open) disclosure.close();
  };
}

interface InfoButtonProps {
  disclosure: InfoDisclosureState;
  /** What the button explains, already translated; it does not change with the state. */
  label: string;
}

/**
 * The "i" in a circle. A real button: Enter and Space work, the state is carried by `aria-expanded` and
 * never by the name, and it is never disabled (reading is allowed on an archived strategy and during a
 * save). The box is 44 by 44 px around a 16 px glyph; the glyph is drawn with attributes and takes its
 * colour from the text class: ink-3 at rest, ink-2 on hover, ink while open.
 */
export function InfoButton({ disclosure, label }: InfoButtonProps) {
  return (
    <button
      type="button"
      ref={disclosure.buttonRef}
      aria-label={label}
      aria-expanded={disclosure.open}
      aria-controls={disclosure.textId}
      onClick={disclosure.toggle}
      onKeyDown={closeOnEscape(disclosure)}
      className={cn(
        "-my-3 inline-flex size-11 shrink-0 items-center justify-center rounded-md",
        disclosure.open ? "text-ink" : "text-ink-3 hover:text-ink-2",
      )}
    >
      <svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="8" cy="8" r="6.75" />
        <circle cx="8" cy="5" r="0.75" fill="currentColor" stroke="none" />
        <path d="M8 7.25v4.5" strokeLinecap="round" />
      </svg>
    </button>
  );
}

/**
 * The text's container. It is ALWAYS in the document, empty while closed, so `aria-controls` always
 * points at something; its paragraphs are rendered only while open, so a closed explanation is neither
 * read nor found.
 */
export function InfoText({ disclosure, children }: { disclosure: InfoDisclosureState; children: ReactNode }) {
  return (
    <div id={disclosure.textId} onKeyDown={closeOnEscape(disclosure)}>
      {disclosure.open ? children : null}
    </div>
  );
}
