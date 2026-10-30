import { Copy } from "lucide-react";
import { useTranslation } from "react-i18next";

import { StatusButton } from "@/shared/ui/StatusButton";

export type CopyButton = "url" | "message";

/** The last copy: the button that was used, whether the browser took the text, and the host it was made with. */
export interface Copied {
  button: CopyButton;
  ok: boolean;
  origin: string | null;
}

export type CopyResult = "none" | "copied" | "failed";

/**
 * What the last copy says about one button; the other button says nothing. "Copied" on the URL's button
 * holds only while the host on screen is still the one that was copied: a host read that answers differently
 * after the copy changes it, and no handler sees that.
 */
export function copyResult(copied: Copied | null, button: CopyButton, origin: string | null): CopyResult {
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
export function CopyAction({
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
      icon={Copy}
      className="min-h-11 rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2 disabled:text-ink-3 disabled:opacity-50"
    />
  );
}
