import { Archive } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/shared/lib/cn";

interface ArchivedNoteProps {
  /** How many archived strategies the exchange has. */
  count: number;
  /** Whether they are in the list now. */
  shown: boolean;
  onToggle: () => void;
  className?: string;
}

/**
 * "Show archived", as the note under the table (L21): the list leaves archived strategies out until the link is
 * pressed, and the note says how many that hides. It toggles the state the checkbox of the search card toggled.
 */
export function ArchivedNote({ count, shown, onToggle, className }: ArchivedNoteProps) {
  const { t } = useTranslation();

  return (
    <p data-testid="archived-note" className={cn("flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[13px] text-ink-3", className)}>
      <Archive aria-hidden="true" className="mr-0.5 size-4 shrink-0" />
      <span>{t(shown ? "strategies.table.archivedShown" : "strategies.table.archivedHidden", { count })}</span>{" "}
      <button type="button" onClick={onToggle} className="text-gain hover:text-gain-bright">
        {t(shown ? "strategies.table.hideArchived" : "strategies.archivedToggle")}
      </button>
    </p>
  );
}
