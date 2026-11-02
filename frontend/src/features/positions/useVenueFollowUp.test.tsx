import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useVenueFollowUp } from "@/features/positions/useVenueFollowUp";
import { confirmedBody, discrepancy, jsonResponse, renderAt, stubApi, unlock } from "@/test/harness";
import type { ConfirmedStub } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const DISCREPANCY = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const CONFIRMED: ConfirmedStub = {
  kind: "ok",
  body: confirmedBody({ being_booked: [discrepancy({ discrepancy_id: DISCREPANCY, reason: null })] }),
};

function Probe() {
  const followUp = useVenueFollowUp(DISCREPANCY);
  return <p data-testid="follow-up">{followUp === null ? "nothing" : followUp.to.hash}</p>;
}

function serve(isAdmin: boolean) {
  const route = (url: string) =>
    url.endsWith("/api/me")
      ? Promise.resolve(jsonResponse({ email: "a@example.com", is_admin: isAdmin, mode: "SIMULATION", dry_run_brake: false }))
      : undefined;
  return stubApi(HEALTH, [], undefined, {}, route, {}, undefined, undefined, CONFIRMED);
}

function requestsTo(fetchMock: ReturnType<typeof stubApi>, path: string) {
  return fetchMock.mock.calls.filter(([input]) => String(input).includes(path));
}

beforeEach(() => {
  unlock();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useVenueFollowUp", () => {
  it("finds the discrepancy for the admin", async () => {
    serve(true);
    renderAt(<Probe />);

    await waitFor(() => expect(screen.getByTestId("follow-up")).toHaveTextContent(`#discrepancy-${DISCREPANCY}`));
  });

  it("asks nothing for anyone else: the list is the admin's, and a refused read per marked line says nothing", async () => {
    const fetchMock = serve(false);
    renderAt(<Probe />);

    await waitFor(() => expect(requestsTo(fetchMock, "/api/me")).not.toEqual([]));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(requestsTo(fetchMock, "/reconciliation/confirmed")).toEqual([]);
    expect(screen.getByTestId("follow-up")).toHaveTextContent("nothing");
  });
});
