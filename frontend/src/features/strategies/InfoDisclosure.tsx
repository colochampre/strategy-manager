import { type ReactNode, type RefObject, useId, useRef } from "react";

/** What the hook shares with the two parts: whether the text is open and the ids that tie them. */
export interface InfoDisclosureState {
  open: boolean;
  textId: string;
  buttonRef: RefObject<HTMLButtonElement | null>;
  toggle: () => void;
  close: () => void;
}

/** STUB (12f.10.12 RED): never opens, until the GREEN owns the open state. */
export function useInfoDisclosure(): InfoDisclosureState {
  const textId = useId();
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  return { open: false, textId, buttonRef, toggle: () => undefined, close: () => undefined };
}

interface InfoButtonProps {
  disclosure: InfoDisclosureState;
  /** What the button explains, already translated; it does not change with the state. */
  label: string;
}

/** STUB (12f.10.12 RED): a button rendered with `aria-expanded="false"` that never opens. */
export function InfoButton({ disclosure, label }: InfoButtonProps) {
  return (
    <button
      type="button"
      ref={disclosure.buttonRef}
      aria-label={label}
      aria-expanded="false"
      aria-controls={disclosure.textId}
      onClick={disclosure.toggle}
    />
  );
}

/** STUB (12f.10.12 RED): the container, without its paragraphs. */
export function InfoText({ disclosure }: { disclosure: InfoDisclosureState; children: ReactNode }) {
  return <div id={disclosure.textId} />;
}
