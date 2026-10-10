import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { StatusButton } from "@/features/strategies/StatusButton";
import { webhookMessage } from "@/features/strategies/webhook-message";
import { webhookUrl } from "@/features/strategies/webhook-url";
import { useWebhookOrigin } from "@/shared/api/webhook-origin";
import { fetchWebhookSecret, useWebhookSecret, WEBHOOK_SECRET_QUERY_KEY } from "@/shared/api/webhook-secret";
import { copyText } from "@/shared/lib/clipboard";

/** Removes the query outright, rather than leaving it to garbage collection after its observers go. */
function evictSecret(queryClient: QueryClient): void {
  queryClient.removeQueries({ queryKey: WEBHOOK_SECRET_QUERY_KEY });
}

interface WebhookMessageProps {
  strategyId: string;
}

type CopyButton = "url" | "message";

/** The last copy: the button that was used, whether the browser took the text, and the host it was made with. */
interface Copied {
  button: CopyButton;
  ok: boolean;
  origin: string | null;
}

type CopyResult = "none" | "copied" | "failed";

/**
 * What the last copy says about one button; the other button says nothing. "Copied" on the URL's button
 * holds only while the host on screen is still the one that was copied: a host read that answers differently
 * after the copy changes it, and no handler sees that. Showing or hiding the secret does not: the clipboard
 * holds the same working URL either way (decision 53).
 */
function copyResult(copied: Copied | null, button: CopyButton, origin: string | null): CopyResult {
  if (copied === null || copied.button !== button) return "none";
  const stale = button === "url" && copied.origin !== origin;
  if (copied.ok) return stale ? "none" : "copied";
  return "failed";
}

/**
 * A Copy button that reads "Copied" itself, so nothing beside it moves (decision 52). A copy that failed
 * keeps the button's ordinary text and says so in a visible text beside it. A button that reads "Copied"
 * stays enabled and copies again.
 */
function CopyAction({
  label,
  result,
  disabled = false,
  onCopy,
}: {
  label: string;
  result: CopyResult;
  disabled?: boolean;
  onCopy: () => void;
}) {
  const { t } = useTranslation();
  const copiedText = t("strategies.webhook.copied");
  return (
    <StatusButton
      texts={[label, copiedText]}
      shown={result === "copied" ? copiedText : label}
      message={result === "copied" ? copiedText : result === "failed" ? t("strategies.webhook.copyFailed") : null}
      tone={result === "failed" ? "failure" : "neutral"}
      onClick={onCopy}
      disabled={disabled}
      className="min-h-11 rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2 disabled:text-ink-3 disabled:opacity-50"
    />
  );
}

/**
 * "Connect a TradingView alert": the webhook URL and the alert message for one
 * strategy, ready to copy.
 *
 * The URL carries a placeholder where the shared secret goes. The secret is
 * REVEALED by one thing only, the "Show secret" click (decision 23); nothing
 * on mount, focus or reconnect asks for it. Two clicks ask the server for it:
 * "Show secret", whose answer lives in the query cache for as long as it is
 * shown, and "Copy URL" while the secret is hidden (decision 53). The second
 * writes the URL that works and shows nothing: its secret is a local value of
 * that one click handler, never in component state, never in the query cache,
 * never in a message, and never replaced by the placeholder in what is written.
 * The shown secret is never copied into component state: it is read from the
 * query result while that result is a success, so a failed or evicted read can
 * never leave a stale value on screen. Leaving the view, or "Hide secret", puts
 * the placeholder back and evicts the query, so nothing keeps the value in the
 * cache for its five-minute garbage-collection window.
 *
 * Keyed by strategy: moving to another strategy's page starts from the
 * placeholder rather than carrying a revealed value across.
 */
export function WebhookMessage({ strategyId }: WebhookMessageProps) {
  return <WebhookMessageView key={strategyId} strategyId={strategyId} />;
}

function WebhookMessageView({ strategyId }: WebhookMessageProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const headingId = useId();
  const urlLabelId = useId();
  const messageLabelId = useId();
  const [requested, setRequested] = useState(false);
  const secret = useWebhookSecret(requested);

  // Leaving the view, by navigation or by unmounting the tree, evicts the secret.
  useEffect(() => () => evictSecret(queryClient), [queryClient]);

  // Shown only for a request this view made: a view that mounts while a cached result still exists
  // (the previous strategy's page, evicted in the same commit) must start from the placeholder.
  const shown = requested && secret.status === "success" ? secret.data : null;
  const failed = requested && secret.status === "error";

  const show = () => {
    if (!requested) setRequested(true);
    else void secret.refetch();
  };

  const hide = () => {
    setRequested(false);
    evictSecret(queryClient);
  };

  const urlValue = shown === null ? t("strategies.webhook.secretPlaceholder") : encodeURIComponent(shown);
  // Read when the block opens, which is when this view mounts. Loading and failing both leave the path alone;
  // only a settled answer says why there is no host.
  const hostRead = useWebhookOrigin();
  const origin = hostRead.status === "success" ? hostRead.data : null;
  const url = webhookUrl(origin, urlValue);
  const hostNote = hostRead.status === "error" ? "hostError" : hostRead.status === "success" && origin === null ? "hostUnset" : null;
  // Built once per render: what the element prints is what its button is given, with no second assembly.
  const message = webhookMessage(strategyId);

  // Which button was used and whether the write worked, never the text. Nothing here touches the secret's
  // request flag or its query.
  const [copied, setCopied] = useState<Copied | null>(null);
  const [copyingUrl, setCopyingUrl] = useState(false);
  const copy = async (button: CopyButton, text: string) => {
    // Recorded with the host of the press, not of the settle: it describes the text that was taken.
    setCopied({ button, ok: await copyText(text), origin });
  };

  // "Copy URL" copies the URL that works. With the secret shown that is the one on screen. With it hidden the
  // secret is asked for here, used for this one write, and dropped: it is the local `secret` below and
  // nowhere else. Nothing is written when the request or the write fails, so the placeholder never reaches the
  // clipboard, and the failure is said as a failed copy, with no text of the error.
  const copyUrl = async () => {
    if (origin === null) return;
    if (shown !== null) {
      await copy("url", url);
      return;
    }
    setCopyingUrl(true);
    let ok = false;
    try {
      const secret = await fetchWebhookSecret();
      ok = await copyText(webhookUrl(origin, encodeURIComponent(secret)));
    } catch {
      // Not logged and not kept: the refusal says nothing of the body it refused.
    }
    setCopyingUrl(false);
    setCopied({ button: "url", ok, origin });
  };

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h2 id={headingId} className="font-display text-base font-semibold text-ink">
        {t("strategies.webhook.title")}
      </h2>
      <p className="text-sm text-ink-2">{t("strategies.webhook.hint")}</p>
      <div className="flex flex-col gap-1">
        <span id={urlLabelId} className="text-xs text-ink-3">
          {t("strategies.webhook.urlLabel")}
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <code
            aria-labelledby={urlLabelId}
            className="min-w-0 grow break-all rounded-md border border-rule bg-panel px-3.5 py-3 font-mono text-xs text-ink-2"
          >
            {url}
          </code>
          {shown === null ? (
            <button
              type="button"
              disabled={requested && secret.isFetching}
              onClick={show}
              className="min-h-11 rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2 disabled:text-ink-3 disabled:opacity-50"
            >
              {t(requested && secret.isFetching ? "strategies.webhook.showing" : "strategies.webhook.show")}
            </button>
          ) : (
            <button
              type="button"
              onClick={hide}
              className="min-h-11 rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2"
            >
              {t("strategies.webhook.hide")}
            </button>
          )}
          <CopyAction
            label={t("strategies.webhook.copyUrl")}
            result={copyResult(copied, "url", origin)}
            // The path alone does not work in TradingView, so with no host there is nothing to copy; and a
            // second click while the secret is on its way would send a second request.
            disabled={origin === null || copyingUrl}
            onCopy={() => void copyUrl()}
          />
        </div>
        {hostNote !== null && <p className="text-xs text-ink-3">{t(`strategies.webhook.${hostNote}`)}</p>}
        {failed && (
          <p role="alert" className="text-sm text-loss">
            {t("strategies.webhook.error")}
          </p>
        )}
      </div>
      <div className="flex flex-col gap-1">
        <span id={messageLabelId} className="text-xs text-ink-3">
          {t("strategies.webhook.messageLabel")}
        </span>
        <pre
          role="group"
          aria-labelledby={messageLabelId}
          tabIndex={0}
          className="overflow-x-auto whitespace-pre-wrap break-all rounded-md border border-rule bg-panel p-3.5 font-mono text-xs leading-relaxed text-ink-2"
        >
          {message}
        </pre>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <CopyAction
            label={t("strategies.webhook.copyMessage")}
            result={copyResult(copied, "message", origin)}
            onCopy={() => void copy("message", message)}
          />
        </div>
      </div>
    </section>
  );
}
