import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { webhookMessage } from "@/features/strategies/webhook-message";
import { webhookUrl } from "@/features/strategies/webhook-url";
import { useWebhookOrigin } from "@/shared/api/webhook-origin";
import { useWebhookSecret, WEBHOOK_SECRET_QUERY_KEY } from "@/shared/api/webhook-secret";

/** Removes the query outright, rather than leaving it to garbage collection after its observers go. */
function evictSecret(queryClient: QueryClient): void {
  queryClient.removeQueries({ queryKey: WEBHOOK_SECRET_QUERY_KEY });
}

interface WebhookMessageProps {
  strategyId: string;
}

/**
 * "Connect a TradingView alert": the webhook URL and the alert message for one
 * strategy, ready to copy.
 *
 * The URL carries a placeholder where the shared secret goes. The secret is
 * requested by one thing only, the "Show secret" click (decision 23); nothing
 * on mount, focus or reconnect asks for it. It is never copied into component
 * state: it is read from the query result while that result is a success, so
 * a failed or evicted read can never leave a stale value on screen. Leaving
 * the view, or "Hide secret", puts the placeholder back and evicts the query,
 * so nothing keeps the value in the cache for its five-minute garbage-collection
 * window.
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
          {webhookMessage(strategyId)}
        </pre>
      </div>
    </section>
  );
}
