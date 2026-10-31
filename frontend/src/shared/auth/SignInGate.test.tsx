import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { page } from "@/shared/auth/reauthenticate";
import { SignInGate } from "@/shared/auth/SignInGate";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { jsonResponse, renderAt } from "@/test/harness";

const ADMIN = { email: "owner@example.com", is_admin: true, mode: "LIVE", dry_run_brake: false };
const USER = { email: "someone@example.com", is_admin: false, mode: "SIMULATION", dry_run_brake: false };

function answerMe(response: () => Promise<Response>) {
  const fetchMock = vi.fn((url: string) =>
    url.endsWith("/api/me") ? response() : Promise.reject(new Error(`unexpected fetch: ${url}`)),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderGate() {
  return renderAt(
    <SignInGate>
      <div>protected content</div>
    </SignInGate>,
  );
}

describe("SignInGate", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    vi.spyOn(page, "reload").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("carries its copy in both locales, never hardcoded", () => {
    for (const locale of [en, es]) {
      expect(locale.auth.gate.checking).toBeTruthy();
      expect(locale.auth.gate.notOpen).toContain("{{email}}");
      expect(locale.auth.gate.unavailable).toBeTruthy();
      expect(locale.auth.gate.retry).toBeTruthy();
      expect(locale.auth.gate.signedOut).toBeTruthy();
      expect(locale.auth.gate.signInAgain).toBeTruthy();
    }
    expect("tokenGate" in en.auth).toBe(false);
    expect("tokenGate" in es.auth).toBe(false);
  });

  it("shows the panel to the admin", async () => {
    answerMe(() => Promise.resolve(jsonResponse(ADMIN)));

    renderGate();

    expect(await screen.findByText("protected content")).toBeInTheDocument();
  });

  it("shows nothing protected while it is still checking", () => {
    answerMe(() => new Promise<Response>(() => undefined));

    renderGate();

    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(en.auth.gate.checking);
  });

  it("tells a signed-in user who is not the admin that the panel is not open yet, by e-mail", async () => {
    answerMe(() => Promise.resolve(jsonResponse(USER)));

    renderGate();

    expect(await screen.findByText(/someone@example\.com/)).toBeInTheDocument();
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
  });

  it("says sign-in cannot be checked on a 503, and retries on request", async () => {
    let calls = 0;
    answerMe(() => {
      calls += 1;
      return Promise.resolve(
        calls === 1 ? jsonResponse({ detail: "down" }, 503) : jsonResponse(ADMIN),
      );
    });

    renderGate();
    fireEvent.click(await screen.findByRole("button", { name: en.auth.gate.retry }));

    expect(await screen.findByText("protected content")).toBeInTheDocument();
    expect(screen.queryByText(en.auth.gate.unavailable)).not.toBeInTheDocument();
  });

  it("offers to sign in again when the session cannot be renewed", async () => {
    answerMe(() => Promise.resolve(jsonResponse({ detail: "unauthorized" }, 401)));
    window.sessionStorage.setItem("sm.reauth_at", String(Date.now()));

    renderGate();
    fireEvent.click(await screen.findByRole("button", { name: en.auth.gate.signInAgain }));

    await waitFor(() => expect(page.reload).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
  });
});
