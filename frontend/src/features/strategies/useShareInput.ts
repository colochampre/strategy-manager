import { useState } from "react";

import { parseDraft, roundToHandle } from "@/features/strategies/share-value";

/** An edit in progress: exactly what the field holds and the last whole position the track was given. */
interface Draft {
  text: string;
  handle: number;
}

/**
 * A share typed into a form that has no strategy yet, so no amount is asked for. It starts from `starting` and
 * says whether the user has edited it since: a share that is still the untouched starting value is asked for in
 * a neutral hint, not refused in red (decision 39).
 */
export function useShareInput(starting: string) {
  const [draft, setDraft] = useState<Draft | null>(null);

  const text = draft?.text ?? starting;
  const reading = parseDraft(text);
  const handle = draft?.handle ?? roundToHandle(starting);

  const changeText = (next: string) => {
    const read = parseDraft(next);
    setDraft({ text: next, handle: read.valid ? roundToHandle(read.canonical) : handle });
  };
  const changeStep = (step: number) => setDraft({ text: String(step), handle: step });

  return { text, reading, handle, edited: draft !== null, changeText, changeStep };
}
