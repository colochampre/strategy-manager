import { type KeyboardEvent, type ReactNode, type RefObject, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { cn } from "@/shared/lib/cn";

/** What the hook shares with the two parts: whether the text is open and the ids that tie them. */
export interface InfoDisclosureState {
  open: boolean;
  textId: string;
  buttonRef: RefObject<HTMLButtonElement | null>;
  /** The floating box beside the button, once it is in the document; the text is drawn into it while open. */
  box: HTMLDivElement | null;
  setBox: (element: HTMLDivElement | null) => void;
  /** A click: pins the text open, or closes a pinned one. */
  toggle: () => void;
  /** Closes the text and puts focus back on the button, whichever element had it. */
  close: () => void;
  /** The pointer entering (true) or leaving (false) the button and its box. */
  hover: (on: boolean) => void;
}

/**
 * The state of one information button (design § B2): closed by default, local to the component that
 * calls it, never stored. Each call owns its own state, so two disclosures open and close independently.
 *
 * It behaves as every tip does (L63, L64): the pointer on the button opens it and leaving closes it; a click
 * or a tap pins it open until a click on it, a press outside or Escape. The keyboard opens it with Enter or
 * Space, as any disclosure button, so tabbing through a form does not open every explanation on the way.
 */
export function useInfoDisclosure(): InfoDisclosureState {
  const [pinned, setPinned] = useState(false);
  const [hovered, setHovered] = useState(false);
  const open = pinned || hovered;
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const textId = useId();
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  // A press outside the button and the box closes it. Focus stays where the press put it.
  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (buttonRef.current?.contains(target) || box?.contains(target)) return;
      setPinned(false);
      setHovered(false);
    };
    document.addEventListener("mousedown", closeOutside);
    return () => document.removeEventListener("mousedown", closeOutside);
  }, [open, box]);

  return {
    open,
    textId,
    buttonRef,
    box,
    setBox,
    // A click on a pinned text closes it even under the pointer, which has to leave and come back to reopen it.
    toggle: () => {
      if (pinned) setHovered(false);
      setPinned(!pinned);
    },
    close: () => {
      setPinned(false);
      setHovered(false);
      buttonRef.current?.focus();
    },
    hover: setHovered,
  };
}

/** Escape closes an open text from the button or from inside the text; focus ends on the button. */
function closeOnEscape(disclosure: InfoDisclosureState) {
  return (event: KeyboardEvent) => {
    if (event.key === "Escape" && disclosure.open) disclosure.close();
  };
}

type BoxAlign = "centre" | "start" | "end";

/** The box is 288 px wide (`w-72`); it keeps 16 px from the screen's edges. */
const BOX_HALF_AND_MARGIN = 144 + 16;

const ALIGN_CLASSES: Record<BoxAlign, string> = {
  centre: "left-1/2 -translate-x-1/2",
  start: "left-0",
  end: "right-0",
};

/**
 * Where the box goes, measured when the button opens it: centred under the button when the screen has room on
 * both sides, otherwise lined up with the button's edge on the side that has none, so a button at the end of a
 * card's header never pushes half the box off the screen. Placement is by class only (the CSP forbids inline
 * styles). A screen that reports no width (no layout) keeps the centre.
 */
function alignOf(button: HTMLElement): BoxAlign {
  const width = document.documentElement.clientWidth;
  if (width === 0) return "centre";
  const rect = button.getBoundingClientRect();
  const centre = rect.left + rect.width / 2;
  if (centre + BOX_HALF_AND_MARGIN > width) return "end";
  if (centre - BOX_HALF_AND_MARGIN < 0) return "start";
  return "centre";
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
  const [align, setAlign] = useState<BoxAlign>("centre");
  const [anchor, setAnchor] = useState<HTMLSpanElement | null>(null);
  const { hover } = disclosure;

  // The pointer is followed on the anchor, which holds the button and the box, with the DOM's own enter and
  // leave: the text reaches the box through a portal, and React would send the leave up its own tree, so
  // moving from the button onto the text would read as leaving.
  useEffect(() => {
    if (anchor === null) return;
    const enter = () => {
      setAlign(alignOf(anchor));
      hover(true);
    };
    const leave = () => hover(false);
    anchor.addEventListener("mouseenter", enter);
    anchor.addEventListener("mouseleave", leave);
    return () => {
      anchor.removeEventListener("mouseenter", enter);
      anchor.removeEventListener("mouseleave", leave);
    };
  }, [anchor, hover]);

  return (
    <span ref={setAnchor} className="relative -my-3 inline-flex shrink-0">
      <button
        type="button"
        ref={disclosure.buttonRef}
        aria-label={label}
        aria-expanded={disclosure.open}
        aria-controls={disclosure.textId}
        onClick={(event) => {
          setAlign(alignOf(event.currentTarget));
          disclosure.toggle();
        }}
        onKeyDown={closeOnEscape(disclosure)}
        className={cn(
          "inline-flex size-11 items-center justify-center rounded-md",
          disclosure.open ? "text-ink" : "text-ink-3 hover:text-ink-2",
        )}
      >
        <svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="8" cy="8" r="6.75" />
          <circle cx="8" cy="5" r="0.75" fill="currentColor" stroke="none" />
          <path d="M8 7.25v4.5" strokeLinecap="round" />
        </svg>
      </button>
      {/* The box is ALWAYS in the document, empty while closed, so `aria-controls` always points at something. It
          floats under the button, in the look of the table tips but wide enough for a paragraph, and fades in. */}
      <div
        id={disclosure.textId}
        ref={disclosure.setBox}
        onKeyDown={closeOnEscape(disclosure)}
        className={cn(
          ALIGN_CLASSES[align],
          "absolute top-full z-20 flex cursor-default w-72 max-w-[calc(100vw-2rem)] flex-col gap-1.5 whitespace-normal break-words rounded-md border border-rule bg-panel-2 px-3 py-2 text-left font-sans text-xs font-normal normal-case tracking-normal text-ink empty:hidden motion-safe:animate-tip-in",
        )}
      />
    </span>
  );
}

/**
 * The text, written by the caller wherever it fits its layout. It renders nothing there: while open its
 * paragraphs are drawn into the floating box the button carries, so a closed explanation is neither read
 * nor found and an open one takes no vertical space.
 */
export function InfoText({ disclosure, children }: { disclosure: InfoDisclosureState; children: ReactNode }) {
  // The box lives next to the button (see InfoButton); the text is written where the caller placed this part
  // and is drawn into the box while open.
  // React sends a portal's events up the React tree, not the DOM one, so Escape is heard here as well.
  return disclosure.open && disclosure.box !== null
    ? createPortal(
        <div onKeyDown={closeOnEscape(disclosure)} className="contents">
          {children}
        </div>,
        disclosure.box,
      )
    : null;
}
