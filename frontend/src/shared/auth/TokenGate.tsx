import { type FormEvent, type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { useTokenStore } from "@/shared/auth/token-store";

interface TokenGateProps {
  children: ReactNode;
}

/**
 * Blocks every child behind a paste-once bearer-token form. The token is
 * held only in `useTokenStore` (localStorage), never in a URL, a log line,
 * or a build-time env variable — design.md §12.
 */
export function TokenGate({ children }: TokenGateProps) {
  const { t } = useTranslation();
  const token = useTokenStore((state) => state.token);
  const setToken = useTokenStore((state) => state.setToken);
  const [draft, setDraft] = useState("");

  if (token) {
    return children;
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = draft.trim();
    if (trimmed.length === 0) {
      return;
    }
    setToken(trimmed);
    setDraft("");
  };

  return (
    <div className="flex min-h-full items-center justify-center bg-ground p-4">
      <form
        onSubmit={handleSubmit}
        className="flex w-full max-w-sm flex-col gap-3 rounded-lg border border-rule bg-panel p-6"
      >
        <h1 className="text-sm font-semibold text-ink">{t("auth.tokenGate.title")}</h1>
        <p className="text-xs text-ink-3">{t("auth.tokenGate.description")}</p>
        <input
          type="password"
          autoComplete="off"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={t("auth.tokenGate.placeholder")}
          aria-label={t("auth.tokenGate.inputLabel")}
          className="rounded-md border border-rule bg-panel-2 px-3 py-2 text-sm text-ink focus:border-gain focus:outline-none"
        />
        <button
          type="submit"
          className="rounded-md bg-gain px-3 py-2 text-sm font-medium text-ground hover:opacity-90"
        >
          {t("auth.tokenGate.submit")}
        </button>
      </form>
    </div>
  );
}
