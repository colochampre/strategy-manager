import { useEffect, useId, useRef, useState } from "react";
import { Pencil, Save, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { StatusButton } from "@/shared/ui/StatusButton";

import { ApiError } from "@/shared/api/client";
import { useRenameStrategy } from "@/shared/api/strategies";
import type { Strategy } from "@/shared/api/types";

interface StrategyTitleProps {
  strategy: Strategy;
}

/**
 * The text of a refused or failed rename: the status (and the archived code) decides, never the server's wording.
 * A 409 without a code is the database's UNIQUE name; the archived and gone texts are the share editor's.
 */
function renameRefusal(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) {
      return error.code === "STRATEGY_ARCHIVED" ? "strategies.detail.share.archived" : "strategies.detail.name.taken";
    }
    if (error.status === 404) return "strategies.detail.share.gone";
  }
  return "strategies.detail.name.saveFailed";
}

/**
 * The strategy's name as the page's title, and the pencil that edits it in place (owner decision 78). An
 * archived strategy has no pencil: the API refuses every change to one.
 */
export function StrategyTitle({ strategy }: StrategyTitleProps) {
  const { t } = useTranslation();
  const fieldId = useId();
  const problemId = useId();
  // The text being edited; `null` while the title is shown.
  const [draft, setDraft] = useState<string | null>(null);
  const rename = useRenameStrategy(strategy.id);
  const field = useRef<HTMLInputElement>(null);
  const pencil = useRef<HTMLButtonElement>(null);
  const wasEditing = useRef(false);
  const editing = draft !== null;

  // Opening focuses the field; closing, by a save or a cancel, gives focus back to the pencil.
  useEffect(() => {
    if (editing) field.current?.focus();
    else if (wasEditing.current) pencil.current?.focus();
    wasEditing.current = editing;
  }, [editing]);

  const close = () => {
    setDraft(null);
    rename.reset();
  };

  // The API does not trim, so the panel does: a name of spaces alone is no name.
  const trimmed = draft?.trim() ?? "";
  const save = () => {
    if (trimmed === "" || rename.isPending) return;
    if (trimmed === strategy.name) {
      close();
      return;
    }
    rename.mutate(trimmed, { onSuccess: close });
  };

  if (draft === null) {
    return (
      <>
        <h1 className="font-display text-3xl font-bold text-ink">{strategy.name}</h1>
        {strategy.archived_at === null && (
          <button
            ref={pencil}
            type="button"
            aria-label={t("strategies.detail.name.rename")}
            onClick={() => setDraft(strategy.name)}
            className="inline-flex size-11 items-center justify-center rounded-md text-ink-3 hover:bg-panel-2 hover:text-ink"
          >
            <Pencil aria-hidden="true" className="size-4" />
          </button>
        )}
      </>
    );
  }

  return (
    <form
      className="flex flex-col gap-1.5"
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={field}
          id={fieldId}
          type="text"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== "Escape" || rename.isPending) return;
            event.preventDefault();
            close();
          }}
          aria-label={t("strategies.detail.name.field")}
          aria-invalid={rename.isError || undefined}
          aria-describedby={rename.isError ? problemId : undefined}
          autoComplete="off"
          className="min-h-11 rounded-md border border-rule bg-ground px-3 py-2 font-display text-xl font-bold text-ink"
        />
        <StatusButton
          texts={[t("strategies.detail.name.save"), t("strategies.detail.name.saving")]}
          shown={rename.isPending ? t("strategies.detail.name.saving") : t("strategies.detail.name.save")}
          message={null}
          submit
          disabled={trimmed === "" || rename.isPending}
          icon={Save}
          className="min-h-11 rounded-md bg-gain px-3 text-sm font-medium text-ground hover:opacity-90 disabled:opacity-50"
        />
        <button
          type="button"
          onClick={close}
          disabled={rename.isPending}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-md border border-rule px-3 text-sm text-ink-2 hover:bg-panel-2 disabled:opacity-50"
        >
          <X aria-hidden="true" className="size-4 shrink-0" />
          {t("strategies.detail.name.cancel")}
        </button>
      </div>
      {rename.isError && (
        <p id={problemId} role="alert" className="text-sm text-loss">
          {t(renameRefusal(rename.error))}
        </p>
      )}
    </form>
  );
}
