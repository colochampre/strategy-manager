import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { CopyAction, copyResult } from "@/features/strategies/CopyAction";
import type { Copied } from "@/features/strategies/CopyAction";
import { webhookUrl } from "@/features/strategies/webhook-url";
import { useWebhookOrigin } from "@/shared/api/webhook-origin";
import { copyText } from "@/shared/lib/clipboard";

interface IssuedWebhookUrlProps {
  /** The secret the server just issued. It lives in this component's props and in nothing it writes. */
  secret: string;
  /** Closes the view that shows it, which is the only way to get rid of it. */
  onDone: () => void;
}

/**
 * The webhook URL WITH its secret, shown once: after a strategy is created and after its secret is
 * regenerated. It is the only place the secret is drawn. The URL is plain text with a Copy button, and a
 * warning says it will not be shown again; "Done" puts it away. The secret is never stored here, logged or
 * put in a request: it arrives as a prop from the one mutation result that holds it.
 *
 * Copy is enabled with no host configured: the secret exists nowhere else, so the path with the secret is
 * copied and the note under the URL says the host goes in front of it.
 */
export function IssuedWebhookUrl({ secret, onDone }: IssuedWebhookUrlProps) {
  const { t } = useTranslation();
  const headingId = useId();
  const urlLabelId = useId();
  const hostRead = useWebhookOrigin();
  const origin = hostRead.status === "success" ? hostRead.data : null;
  const hostNote = hostRead.status === "error" ? "hostError" : hostRead.status === "success" && origin === null ? "hostUnset" : null;
  const url = webhookUrl(origin, encodeURIComponent(secret));
  const [copied, setCopied] = useState<Copied | null>(null);

  const copy = async () => {
    setCopied({ button: "url", ok: await copyText(url), origin });
  };

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3 rounded-md border border-rule bg-panel-2 p-4">
      <h3 id={headingId} className="text-sm font-semibold text-ink">
        {t("strategies.webhook.issuedTitle")}
      </h3>
      <p className="text-sm text-ink-2">{t("strategies.webhook.issuedWarning")}</p>
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
          <CopyAction label={t("strategies.webhook.copyUrl")} result={copyResult(copied, "url", origin)} onCopy={() => void copy()} />
        </div>
        {hostNote !== null && <p className="text-xs text-ink-3">{t(`strategies.webhook.${hostNote}`)}</p>}
      </div>
      <div className="flex justify-end">
        <button
          type="button"
          onClick={onDone}
          className="inline-flex min-h-11 items-center rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2"
        >
          {t("strategies.webhook.issuedDone")}
        </button>
      </div>
    </section>
  );
}
