import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TopBar } from "@/shared/layout/TopBar";
import { jsonResponse, lock, renderAt, resetExchangeScope, stubApi, unlock } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: false } } as const;

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

function poolsRequests(fetchMock: ReturnType<typeof stubApi>) {
  return fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/pools"));
}

describe("who is signed in, in the top bar", () => {
  function signedInAs(displayName: string | null) {
    stubApi(HEALTH, [], undefined, {}, (url) =>
      url.endsWith("/api/me")
        ? Promise.resolve(
            jsonResponse({
              email: "owner@example.com",
              is_admin: true,
              mode: "LIVE",
              dry_run_brake: false,
              display_name: displayName,
            }),
          )
        : undefined,
    );
    renderAt(<TopBar />, "/settings");
  }

  it("is the name the user chose (decision 17)", async () => {
    signedInAs("Ana");

    expect(await screen.findByText("Ana")).toBeInTheDocument();
    expect(screen.queryByText("owner@example.com")).toBeNull();
  });

  it("is the e-mail until there is a name", async () => {
    signedInAs(null);

    expect(await screen.findByText("owner@example.com")).toBeInTheDocument();
  });
});

describe("the exchange tabs in the top bar", () => {
  it.each(["/", "/strategies", "/strategies/5b0c7a52-6f43-4d6e-9c1c-0c2f3f3f2a11"])(
    "are drawn on %s, twice: in the bar and as the row below it",
    async (path) => {
      stubApi(HEALTH);
      renderAt(<TopBar />, path);

      expect(await screen.findAllByRole("navigation", { name: "Exchanges" })).toHaveLength(2);
    },
  );

  it.each(["/settings", "/discrepancies"])(
    "are not drawn on %s, and the exchange scope is not read there (note N7)",
    async (path) => {
      const fetchMock = stubApi(HEALTH);
      renderAt(<TopBar />, path);

      // The mode badge reads /api/me: once it has answered, the bar has had every chance to ask for the pools.
      await screen.findByText(/^(Simulation forced|Mode unknown)$/);
      await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(0));
      expect(screen.queryByRole("navigation", { name: "Exchanges" })).not.toBeInTheDocument();
      expect(poolsRequests(fetchMock)).toHaveLength(0);
    },
  );

  it("do read the pools on the Overview, which proves the check above can see a read", async () => {
    const fetchMock = stubApi(HEALTH);
    renderAt(<TopBar />, "/");

    await screen.findAllByRole("navigation", { name: "Exchanges" });
    await waitFor(() => expect(poolsRequests(fetchMock).length).toBeGreaterThan(0));
  });
});
