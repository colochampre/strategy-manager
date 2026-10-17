import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DiscrepanciesPage } from "@/features/discrepancies/DiscrepanciesPage";
import { booking, confirmedBody, discrepancy, lock, renderAt, stubApi, unlock } from "@/test/harness";
import type { ConfirmedStub } from "@/test/harness";

/**
 * The page's read states (spec "The Discrepancies Page States Its Read And Never Reads As An All-Clear Without
 * Having Looked"; owner decision 66; prototype examples 4, 6, 8, 9 and 10). K row 8: a failed read is never an
 * all-clear. K row 14: dry run is never an all-clear.
 */

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: false } } as const;
const ALL_CLEAR = "Nothing needs you. The venue agrees with the ledger on every confirmed comparison.";
const NO_BOOKING = "No booking in the last 30 days.";
const FAILED = "Discrepancies could not be read, so this page cannot say whether anything needs you.";
const DRY_RUN = "The comparison with the venue does not run in dry run, so nothing is checked here.";

function mountPage(confirmed: ConfirmedStub) {
  const fetchMock = stubApi(HEALTH, [], undefined, {}, undefined, {}, undefined, undefined, confirmed);
  renderAt(<DiscrepanciesPage />, "/discrepancies");
  return fetchMock;
}

function sectionNames(): string[] {
  return screen.queryAllByRole("heading", { level: 2 }).map((heading) => heading.textContent ?? "");
}

beforeEach(() => {
  unlock();
});
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
});

describe("the read states", () => {
  it("says it is reading while the first read has not answered, with no list and no all-clear", () => {
    mountPage({ kind: "pending" });

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Reading discrepancies…");
    expect(screen.getByRole("heading", { level: 1, name: "Discrepancies" })).toBeInTheDocument();
    expect(sectionNames()).toEqual([]);
    expect(screen.queryByText(/Nothing needs you/)).not.toBeInTheDocument();
    expect(screen.queryByText(NO_BOOKING)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Read again" })).not.toBeInTheDocument();
  });

  it.each([
    ["a 500", { kind: "status", status: 500, body: { detail: "down" } } as const],
    ["a 404 from an API that predates the route", { kind: "status", status: 404, body: { detail: "Not Found" } } as const],
    ["a network error", { kind: "network-error" } as const],
    ["a body that is not the shape", { kind: "ok", body: { read_at: "2026-10-16T21:40:03Z" } } as const],
  ])("never says nothing needs the owner after a first read that failed with %s", async (_name, stub) => {
    mountPage(stub);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(FAILED);
    expect(alert).toHaveClass("text-loss");
    expect(screen.getByRole("button", { name: "Read again" })).toBeInTheDocument();
    expect(sectionNames()).toEqual([]);
    expect(screen.queryByText(/Nothing needs you/)).not.toBeInTheDocument();
    expect(screen.queryByText(NO_BOOKING)).not.toBeInTheDocument();
  });

  it("reads again when the button is pressed after a failure, and then draws what it read", async () => {
    mountPage({
      kind: "sequence",
      stubs: [{ kind: "status", status: 500, body: { detail: "down" } }, { kind: "ok", body: confirmedBody() }],
    });
    await screen.findByRole("alert");

    fireEvent.click(screen.getByRole("button", { name: "Read again" }));

    expect(await screen.findByText(ALL_CLEAR)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps the last lists after a failed refresh, with Last read in loss and since when it could not be refreshed", async () => {
    mountPage({
      kind: "sequence",
      stubs: [
        { kind: "ok", body: confirmedBody({ read_at: "2026-10-16T21:38:12Z", needs_owner: [discrepancy()] }) },
        { kind: "status", status: 500, body: { detail: "down" } },
      ],
    });
    expect(await screen.findByText("21:38:12 UTC")).toBeInTheDocument();
    expect(screen.queryByText(/could not be refreshed/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Read again" }));

    const stale = await screen.findByText("Could not be refreshed since 21:38:12 UTC.");
    expect(stale).toHaveClass("text-loss");
    expect(screen.getByText("Last read")).toHaveClass("text-loss");
    expect(screen.getByText("21:38:12 UTC")).toHaveClass("text-loss");
    expect(sectionNames()).toEqual(["Needs you", "Booked automatically"]);
    expect(screen.queryByText(/Nothing needs you/)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("writes the time of the last read in UTC, with no loss colour while the read is good", async () => {
    mountPage({ kind: "ok", body: confirmedBody() });

    const time = await screen.findByText("21:40:03 UTC");
    expect(time).not.toHaveClass("text-loss");
    expect(screen.getByText("Last read")).not.toHaveClass("text-loss");
    expect(screen.getByRole("button", { name: "Read again" })).toBeInTheDocument();
  });

  it("says the comparison does not run in dry run, and draws no list even when the route holds rows (note N3)", async () => {
    mountPage({
      kind: "ok",
      body: confirmedBody({
        dry_run: true,
        needs_owner: [discrepancy()],
        being_booked: [discrepancy({ reason: null })],
        booked: [booking()],
      }),
    });

    const sentence = await screen.findByText(DRY_RUN);
    expect(sentence).toHaveAttribute("role", "status");
    expect(sentence).toHaveClass("border-rule-strong");
    expect(sentence).not.toHaveClass("text-loss", "border-loss", "text-decision", "border-decision");
    expect(sectionNames()).toEqual([]);
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText(/Nothing needs you/)).not.toBeInTheDocument();
    expect(screen.queryByText(NO_BOOKING)).not.toBeInTheDocument();
    expect(screen.getByText("21:40:03 UTC")).toBeInTheDocument();
  });

  it("draws no list in dry run when the lists are empty either: it is never an all-clear", async () => {
    mountPage({ kind: "ok", body: confirmedBody({ dry_run: true }) });

    await screen.findByText(DRY_RUN);
    expect(sectionNames()).toEqual([]);
    expect(screen.queryByText(/Nothing needs you/)).not.toBeInTheDocument();
  });

  it("draws both all-clear sentences, and no Being booked section, when nothing is in any list", async () => {
    mountPage({ kind: "ok", body: confirmedBody() });

    expect(await screen.findByText(ALL_CLEAR)).toBeInTheDocument();
    expect(screen.getByText(NO_BOOKING)).toBeInTheDocument();
    expect(sectionNames()).toEqual(["Needs you", "Booked automatically"]);
    expect(screen.getByText("The last 30 days, newest first, at most 100.")).toBeInTheDocument();
  });

  it("says only 'Nothing needs you.' while something is being booked and nothing needs the owner", async () => {
    mountPage({ kind: "ok", body: confirmedBody({ being_booked: [discrepancy({ reason: null })] }) });

    expect(await screen.findByText("Nothing needs you.")).toBeInTheDocument();
    expect(screen.queryByText(ALL_CLEAR)).not.toBeInTheDocument();
    expect(sectionNames()).toEqual(["Needs you", "Being booked", "Booked automatically"]);
    expect(screen.getByText("Nothing here needs you. If it cannot be booked, it moves to Needs you.")).toBeInTheDocument();
  });

  it("does not say 'Nothing needs you' when an item needs the owner", async () => {
    mountPage({ kind: "ok", body: confirmedBody({ needs_owner: [discrepancy()] }) });

    await screen.findByRole("heading", { level: 2, name: "Needs you" });
    await waitFor(() => expect(screen.getByText("21:40:03 UTC")).toBeInTheDocument());
    expect(screen.queryByText(/Nothing needs you/)).not.toBeInTheDocument();
  });

  it("draws the title, its sentence, the read line and then the sections in order", async () => {
    mountPage({
      kind: "ok",
      body: confirmedBody({
        needs_owner: [discrepancy()],
        being_booked: [discrepancy({ reason: null })],
        booked: [booking()],
      }),
    });

    await screen.findByRole("heading", { level: 2, name: "Booked automatically" });
    expect(sectionNames()).toEqual(["Needs you", "Being booked", "Booked automatically"]);
    const title = screen.getByRole("heading", { level: 1, name: "Discrepancies" });
    const lede = screen.getByText(
      "Where the exchange and the ledger still disagree after repeated comparisons. A close the system can attribute to one strategy is booked automatically; the rest is listed under Needs you.",
    );
    const read = screen.getByText("Last read");
    const [needs, being, booked] = screen.getAllByRole("heading", { level: 2 }) as [HTMLElement, HTMLElement, HTMLElement];
    const inOrder = [title, lede, read, needs, being, booked];
    for (let index = 1; index < inOrder.length; index += 1) {
      const before = inOrder[index - 1] as HTMLElement;
      const after = inOrder[index] as HTMLElement;
      expect(before.compareDocumentPosition(after) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  });

  it("makes one request to the route", async () => {
    const fetchMock = mountPage({ kind: "ok", body: confirmedBody() });

    await screen.findByText(ALL_CLEAR);
    const requests = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/reconciliation/confirmed"));
    expect(requests).toHaveLength(1);
  });
});
