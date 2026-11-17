import { Pencil } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { StrategyDescriptionEditor } from "@/features/strategies/StrategyDescriptionEditor";
import type { Strategy } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";
import { LinkifiedText } from "@/shared/ui/LinkifiedText";

/**
 * The text, folded to four lines when it is longer, so a long description never pushes the page below it out of
 * place; Show more unfolds it. Whether it is longer is measured, not guessed from its length: a narrow column folds
 * a text a wide one holds.
 */
function FoldedText({ text }: { text: string }) {
  const { t } = useTranslation();
  const body = useRef<HTMLParagraphElement>(null);
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);

  useLayoutEffect(() => {
    const element = body.current;
    if (element === null || open) return;
    const measure = () => setOverflows(element.scrollHeight > element.clientHeight + 1);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [text, open]);

  return (
    <div className="flex flex-col items-start gap-1">
      {/* Plain text: React escapes it; only http and https URLs become links, nothing is parsed as HTML or Markdown. */}
      <p ref={body} className={cn("whitespace-pre-line break-words text-sm text-ink", !open && "line-clamp-4")}>
        <LinkifiedText text={text} />
      </p>
      {(overflows || open) && (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className="min-h-11 text-xs text-ink-3 hover:text-ink-2"
        >
          {t(open ? "strategies.description.less" : "strategies.description.more")}
        </button>
      )}
    </div>
  );
}

/** The heading's row: as tall as the author's pencil on both pages, so the text below starts at one height. */
function Heading({ children }: { children?: ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-11 items-center gap-1">
      <h2 className="text-xs font-semibold text-ink-2">{t("strategies.description.publicHeading")}</h2>
      {children}
    </div>
  );
}

/**
 * Another author's description. One with none says so in the place the text would take, as the author's own page does,
 * so the page below starts at one height on both (owner, 2026-11-17).
 */
export function PublicDescription({ text }: { text: string | null }) {
  const { t } = useTranslation();
  return (
    <section data-testid="public-description" className="flex flex-col">
      <Heading />
      {text === null ? <p className="text-sm text-ink-3">{t("strategies.description.none")}</p> : <FoldedText text={text} />}
    </section>
  );
}

/**
 * The author's description, in the place another author's page shows it, edited in place from a pencil as the name
 * is (owner, 2026-11-17). An archived strategy has no pencil: the API refuses every change to one.
 */
export function AuthorDescription({ strategy }: { strategy: Pick<Strategy, "id" | "description" | "archived_at"> }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const pencil = useRef<HTMLButtonElement>(null);
  const wasEditing = useRef(false);

  // Closing, by a save or a cancel, gives focus back to the pencil; the field takes it on opening.
  useEffect(() => {
    if (!editing && wasEditing.current) pencil.current?.focus();
    wasEditing.current = editing;
  }, [editing]);

  return (
    <section data-testid="strategy-description" className="flex flex-col">
      <Heading>
        {strategy.archived_at === null && !editing && (
          <button
            ref={pencil}
            type="button"
            aria-label={t("strategies.description.edit")}
            onClick={() => setEditing(true)}
            className="inline-flex size-11 items-center justify-center rounded-md text-ink-3 hover:bg-panel-2 hover:text-ink"
          >
            <Pencil aria-hidden="true" className="size-4" />
          </button>
        )}
      </Heading>
      {editing ? (
        <StrategyDescriptionEditor strategy={strategy} onDone={() => setEditing(false)} />
      ) : strategy.description === null ? (
        <p className="text-sm text-ink-3">{t("strategies.description.none")}</p>
      ) : (
        <FoldedText text={strategy.description} />
      )}
    </section>
  );
}
