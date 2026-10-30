import { useId, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { CopyAction, copyResult } from "@/features/strategies/CopyAction";
import type { Copied } from "@/features/strategies/CopyAction";
import { IssuedWebhookUrl } from "@/features/strategies/IssuedWebhookUrl";
import { RegenerateSecretDialog } from "@/features/strategies/RegenerateSecretDialog";
import { webhookMessage } from "@/features/strategies/webhook-message";
import { webhookUrl } from "@/features/strategies/webhook-url";
import { useRegenerateWebhookSecret } from "@/shared/api/strategies";
import { useWebhookOrigin } from "@/shared/api/webhook-origin";
import { copyText } from "@/shared/lib/clipboard";

interface WebhookMessageProps {
  strategyId: string;
  /** An archived strategy's secret cannot be regenerated: the API refuses every change to one. */
  archived: boolean;
}

/**
 * "Connect a TradingView alert": the webhook URL and the alert message for one strategy.
 *
 * The URL carries a placeholder where the strategy's secret goes. The secret is stored only as a hash, so
 * this panel can never read it back: the one time it is drawn is the moment it is issued, by creating the
 * strategy or by "Regenerate secret" here, and that view (`IssuedWebhookUrl`) says it will not be shown
 * again. Regenerating asks first, because the old secret stops working at once. The new secret lives in
 * the one mutation result, which leaves the cache when this view is left or "Done" is pressed; nothing
 * here writes it to storage, to a query key or to the console.
 *
 * Keyed by strategy: moving to another strategy's page starts from the placeholder rather than carrying a
 * secret across.
 */
export function WebhookMessage({ strategyId, archived }: WebhookMessageProps) {
  return <WebhookMessageView key={strategyId} strategyId={strategyId} archived={archived} />;
}

function WebhookMessageView({ strategyId, archived }: WebhookMessageProps) {
  const { t } = useTranslation();
  const headingId = useId();
  const urlLabelId = useId();
  const messageLabelId = useId();
  const regenerate = useRegenerateWebhookSecret(strategyId);
  const [asking, setAsking] = useState(false);
  const issued = regenerate.data ?? null;

  // Read when the block opens, which is when this view mounts. Loading and failing both leave the path alone;
  // only a settled answer says why there is no host.
  const hostRead = useWebhookOrigin();
  const origin = hostRead.status === "success" ? hostRead.data : null;
  const url = webhookUrl(origin, t("strategies.webhook.secretPlaceholder"));
  const hostNote = hostRead.status === "error" ? "hostError" : hostRead.status === "success" && origin === null ? "hostUnset" : null;
  // Built once per render: what the element prints is what its button is given, with no second assembly.
  const message = webhookMessage(strategyId);

  const [copied, setCopied] = useState<Copied | null>(null);
  const copyMessage = async () => {
    setCopied({ button: "message", ok: await copyText(message), origin });
  };

  const stopAsking = () => {
    regenerate.reset();
    setAsking(false);
  };

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h2 id={headingId} className="font-display text-base font-semibold text-ink">
        {t("strategies.webhook.title")}
      </h2>
      <p className="text-sm text-ink-2">{t("strategies.webhook.hint")}</p>
      {issued !== null ? (
        <IssuedWebhookUrl secret={issued} onDone={() => regenerate.reset()} />
      ) : (
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
            <button
              type="button"
              disabled={archived}
              onClick={() => setAsking(true)}
              className="inline-flex min-h-11 items-center gap-1.5 rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2 disabled:text-ink-3 disabled:opacity-50"
            >
              <RefreshCw aria-hidden="true" className="size-4 shrink-0" />
              {t("strategies.webhook.regenerate")}
            </button>
          </div>
          {hostNote !== null && <p className="text-xs text-ink-3">{t(`strategies.webhook.${hostNote}`)}</p>}
        </div>
      )}
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
            onCopy={() => void copyMessage()}
          />
        </div>
      </div>
      {asking && issued === null && (
        <RegenerateSecretDialog
          pending={regenerate.isPending}
          error={regenerate.error}
          onConfirm={() => regenerate.mutate(undefined, { onSuccess: () => setAsking(false) })}
          onCancel={stopAsking}
        />
      )}
    </section>
  );
}
