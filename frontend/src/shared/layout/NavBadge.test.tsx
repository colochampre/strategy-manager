import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import i18n from "@/shared/i18n";
import { NavBadge } from "@/shared/layout/NavBadge";
import { booking, confirmedBody, discrepancy, lock, stubApi, unlock } from "@/test/harness";
import type { ConfirmedStub } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: false } } as const;

function renderBadge(confirmed: ConfirmedStub, corner = false) {
  stubApi(HEALTH, [], undefined, {}, undefined, {}, undefined, undefined, confirmed);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NavBadge corner={corner} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { client, ...view };
}

function needing(count: number) {
  return confirmedBody({ needs_owner: Array.from({ length: count }, () => discrepancy()) });
}

beforeEach(unlock);
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

describe("NavBadge", () => {
  it("draws the count of the items that need the owner, with its words for a screen reader", async () => {
    renderBadge({ kind: "ok", body: needing(12) });

    const number = await screen.findByText("12");
    expect(number).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText(/12 discrepancies need you/)).toHaveClass("sr-only");
  });

  it("uses the singular for one", async () => {
    renderBadge({ kind: "ok", body: needing(1) });

    expect(await screen.findByText("1")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText(/1 discrepancy needs you/)).toHaveClass("sr-only");
  });

  it("says its words in Spanish, to usted", async () => {
    await i18n.changeLanguage("es");
    renderBadge({ kind: "ok", body: needing(12) });

    await screen.findByText("12");
    expect(screen.getByText(/12 discrepancias requieren su atención/)).toBeInTheDocument();
  });

  it("counts the items of needs_owner, not the number the body carries beside them", async () => {
    renderBadge({ kind: "ok", body: { ...needing(3), needs_owner_count: 9 } });

    expect(await screen.findByText("3")).toBeInTheDocument();
    expect(screen.queryByText("9")).not.toBeInTheDocument();
  });

  it("is red, with the loss token, and never amber", async () => {
    renderBadge({ kind: "ok", body: needing(2) });

    const badge = await screen.findByText("2");
    expect(badge).toHaveClass("bg-loss");
    expect(badge.className).not.toMatch(/amber|decision/);
  });

  it("lifts itself to the corner of its cell when asked, and does not otherwise", async () => {
    const { unmount } = renderBadge({ kind: "ok", body: needing(2) }, true);
    const cornered = await screen.findByText("2");
    expect(cornered).toHaveClass("absolute");
    unmount();

    renderBadge({ kind: "ok", body: needing(2) });
    expect(await screen.findByText("2")).not.toHaveClass("absolute");
  });

  it("draws nothing at zero", async () => {
    const fetchMock = stubApi(HEALTH, [], undefined, {}, undefined, {}, undefined, undefined, {
      kind: "ok",
      body: needing(0),
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={client}>
        <NavBadge />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/reconciliation/confirmed"))).toBe(true),
    );
    await waitFor(() => expect(client.getQueryState(["reconciliation", "confirmed"])?.status).toBe("success"));
    expect(container).toBeEmptyDOMElement();
  });

  it("draws nothing while the read is loading", () => {
    const { container } = renderBadge({ kind: "pending" });

    expect(container).toBeEmptyDOMElement();
  });

  it("draws nothing when the first read failed", async () => {
    const { client, container } = renderBadge({ kind: "status", status: 500, body: { detail: "down" } });

    await waitFor(() => expect(client.getQueryState(["reconciliation", "confirmed"])?.status).toBe("error"));
    expect(container).toBeEmptyDOMElement();
  });

  it("draws nothing for a body that is not the route's shape", async () => {
    const { client, container } = renderBadge({ kind: "ok", body: { needs_owner: [] } });

    await waitFor(() => expect(client.getQueryState(["reconciliation", "confirmed"])?.status).toBe("error"));
    expect(container).toBeEmptyDOMElement();
  });

  it("never counts an item being booked or a booking", async () => {
    const { client, container } = renderBadge({
      kind: "ok",
      body: confirmedBody({
        being_booked: [discrepancy({ reason: null })],
        booked: [booking(), booking()],
      }),
    });

    await waitFor(() => expect(client.getQueryState(["reconciliation", "confirmed"])?.status).toBe("success"));
    expect(container).toBeEmptyDOMElement();
  });

  it("draws nothing when dry_run is true, whatever the lists hold (note N3)", async () => {
    const { client, container } = renderBadge({ kind: "ok", body: { ...needing(2), dry_run: true } });

    await waitFor(() => expect(client.getQueryState(["reconciliation", "confirmed"])?.status).toBe("success"));
    expect(container).toBeEmptyDOMElement();
  });

  it("keeps the last count after a refresh fails", async () => {
    const { client } = renderBadge({
      kind: "sequence",
      stubs: [
        { kind: "ok", body: needing(2) },
        { kind: "status", status: 500, body: { detail: "down" } },
      ],
    });
    expect(await screen.findByText("2")).toBeInTheDocument();

    await client.refetchQueries({ queryKey: ["reconciliation", "confirmed"] });

    await waitFor(() => expect(client.getQueryState(["reconciliation", "confirmed"])?.fetchStatus).toBe("idle"));
    expect(client.getQueryState(["reconciliation", "confirmed"])?.status).toBe("error");
    expect(screen.getByText("2")).toBeInTheDocument();
  });
});
