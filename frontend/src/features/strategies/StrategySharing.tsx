import { X } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { CopyAction } from "@/features/strategies/CopyAction";
import type { CopyResult } from "@/features/strategies/CopyAction";
import { ApiError } from "@/shared/api/client";
import { useInviteCodes, useIssueInviteCode, useRevokeInviteCode } from "@/shared/api/strategies";
import type { InviteCode, IssuedInviteCode, Strategy } from "@/shared/api/types";
import { copyText } from "@/shared/lib/clipboard";
import { dateTimeText } from "@/shared/lib/figure-text";

interface StrategySharingProps {
  strategy: Strategy;
}

const KEY = "strategies.sharing";

/** The last copy: the text copied and whether the browser took it. "Copied" holds only for the text on screen. */
interface Copied {
  text: string;
  ok: boolean;
}

function copyResultOf(copied: Copied | null, text: string): CopyResult {
  if (copied === null) return "none";
  if (!copied.ok) return "failed";
  return copied.text === text ? "copied" : "none";
}

function useCopy() {
  const [copied, setCopied] = useState<Copied | null>(null);
  const copy = async (text: string) => {
    setCopied({ text, ok: await copyText(text) });
  };
  return { copied, copy };
}

/**
 * How the author shares a strategy that is not public (decision 41), in its settings: a LINK strategy shows its
 * link, a PRIVATE one its invitation codes. A public strategy is on Explore and needs neither.
 */
export function StrategySharing({ strategy }: StrategySharingProps) {
  if (strategy.visibility === "LINK" && strategy.share_token !== null) {
    return <ShareLink strategyId={strategy.id} token={strategy.share_token} />;
  }
  if (strategy.visibility === "PRIVATE") return <InviteCodes strategy={strategy} />;
  return null;
}

/** The address of the strategy's public page that opens it to whoever holds it. */
export function shareLink(origin: string, strategyId: string, token: string): string {
  return `${origin}/strategies/explore/${encodeURIComponent(strategyId)}?link=${encodeURIComponent(token)}`;
}

function ShareLink({ strategyId, token }: { strategyId: string; token: string }) {
  const { t } = useTranslation();
  const headingId = useId();
  const url = shareLink(window.location.origin, strategyId, token);
  const { copied, copy } = useCopy();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <h3 id={headingId} className="text-xs font-semibold text-ink-2">
        {t(`${KEY}.linkTitle`)}
      </h3>
      <div className="flex flex-wrap items-center gap-2">
        <code className="min-w-0 grow break-all rounded-md border border-rule bg-ground px-3 py-2.5 font-mono text-xs text-ink-2">
          {url}
        </code>
        <CopyAction label={t(`${KEY}.copyLink`)} result={copyResultOf(copied, url)} onCopy={() => void copy(url)} />
      </div>
      <p className="text-xs text-ink-3">{t(`${KEY}.linkHint`)}</p>
    </section>
  );
}

/** The text of a refused or failed creation: the status and the code decide, never the server's wording. */
function createRefusal(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409 && error.code === "STRATEGY_NOT_PRIVATE") return `${KEY}.createRefused.notPrivate`;
    if (error.status === 409 && error.code === "AUTHOR_HAS_NO_DISPLAY_NAME") return "strategies.visibility.needsName";
    if (error.status === 409 && error.code === "STRATEGY_ARCHIVED") return `${KEY}.createRefused.archived`;
    if (error.status === 404) return `${KEY}.createRefused.gone`;
  }
  return `${KEY}.createRefused.failed`;
}

/** A 404 is a code that no longer opens anything: spent, expired or revoked meanwhile. */
function revokeRefusal(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) return `${KEY}.revokeRefused.notLive`;
  return `${KEY}.revokeRefused.failed`;
}

const BUTTON = "inline-flex min-h-11 items-center rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2 disabled:text-ink-3 disabled:opacity-50";

/**
 * A PRIVATE strategy's codes: "Create code" makes one and shows it once; the unused ones are listed by their
 * last four characters and their expiry, each with an ✕ that revokes it. An archived strategy makes no new code
 * (the API refuses it), and its unused ones can still be revoked.
 */
function InviteCodes({ strategy }: { strategy: Strategy }) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const codes = useInviteCodes(strategy.id, true);
  const issue = useIssueInviteCode(strategy.id);
  const revoke = useRevokeInviteCode(strategy.id);
  const archived = strategy.archived_at !== null;
  const locale = i18n.language;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 id={headingId} className="text-xs font-semibold text-ink-2">
          {t(`${KEY}.codesTitle`)}
        </h3>
        <button type="button" onClick={() => issue.mutate()} disabled={archived || issue.isPending} className={BUTTON}>
          {t(`${KEY}.create`)}
        </button>
      </div>
      <p className="text-xs text-ink-3">{t(`${KEY}.codesHint`)}</p>
      {issue.status === "success" && <IssuedCode issued={issue.data} locale={locale} onDone={() => issue.reset()} />}
      {issue.status === "error" && (
        <p role="alert" className="text-xs text-loss">
          {t(createRefusal(issue.error))}
        </p>
      )}
      {codes.status === "error" && <p className="text-xs text-loss">{t(`${KEY}.loadFailed`)}</p>}
      {codes.status === "success" && codes.data.length === 0 && <p className="text-xs text-ink-3">{t(`${KEY}.none`)}</p>}
      {codes.status === "success" && codes.data.length > 0 && (
        <ul aria-label={t(`${KEY}.listLabel`)} className="flex flex-col divide-y divide-rule">
          {codes.data.map((code) => (
            <CodeRow
              key={code.id}
              code={code}
              locale={locale}
              disabled={revoke.isPending}
              onRevoke={() => revoke.mutate(code.id)}
            />
          ))}
        </ul>
      )}
      {revoke.status === "error" && (
        <p role="alert" className="text-xs text-loss">
          {t(revokeRefusal(revoke.error))}
        </p>
      )}
    </section>
  );
}

function CodeRow({
  code,
  locale,
  disabled,
  onRevoke,
}: {
  code: InviteCode;
  locale: string;
  disabled: boolean;
  onRevoke: () => void;
}) {
  const { t } = useTranslation();
  const revokeLabel = t(`${KEY}.revoke`, { hint: code.hint });
  return (
    <li className="flex items-center justify-between gap-3 py-1.5">
      <span className="flex flex-col">
        <span className="font-mono text-sm text-ink">{`····-${code.hint}`}</span>
        <span className="text-xs text-ink-3">{t(`${KEY}.expires`, { when: dateTimeText(code.expires_at, locale) })}</span>
      </span>
      <button
        type="button"
        aria-label={revokeLabel}
        title={revokeLabel}
        onClick={onRevoke}
        disabled={disabled}
        className="inline-flex size-11 items-center justify-center rounded-md text-ink-2 hover:bg-panel-2 hover:text-loss disabled:opacity-50"
      >
        <X aria-hidden="true" className="size-4.5" />
      </button>
    </li>
  );
}

/**
 * The code just made, shown once: it lives in the mutation's result, which nothing caches once this view is put
 * away ("Done" resets the mutation, `gcTime: 0`). Only its hash is stored, so it can never be shown again.
 */
function IssuedCode({ issued, locale, onDone }: { issued: IssuedInviteCode; locale: string; onDone: () => void }) {
  const { t } = useTranslation();
  const headingId = useId();
  const { copied, copy } = useCopy();
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2 rounded-md border border-rule bg-panel-2 p-3">
      <h4 id={headingId} className="text-sm font-semibold text-ink">
        {t(`${KEY}.issuedTitle`)}
      </h4>
      <p className="text-xs text-ink-2">{t(`${KEY}.issuedWarning`)}</p>
      <div className="flex flex-wrap items-center gap-2">
        <code className="grow rounded-md border border-rule bg-panel px-3 py-2.5 font-mono text-base tracking-wider text-ink">
          {issued.code}
        </code>
        <CopyAction
          label={t(`${KEY}.copyCode`)}
          result={copyResultOf(copied, issued.code)}
          onCopy={() => void copy(issued.code)}
        />
      </div>
      <p className="text-xs text-ink-3">{t(`${KEY}.expires`, { when: dateTimeText(issued.expires_at, locale) })}</p>
      <div className="flex justify-end">
        <button type="button" onClick={onDone} className={BUTTON}>
          {t(`${KEY}.done`)}
        </button>
      </div>
    </section>
  );
}
