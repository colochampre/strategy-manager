import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PositionsTable } from "@/features/positions/PositionsTable";
import i18n from "@/shared/i18n";
import { jsonResponse, lock, openPosition, renderAt, setViewport, unlock } from "@/test/harness";

/**
 * "Close now" (subscriber-safety SS.9): each open position has a button that opens a dialog naming the symbol and
 * the size. Only confirming sends `POST /api/positions/{allocation_id}/close`; cancelling sends nothing.
 */

const ALLOCATION = "aaaaaaaa-0000-4000-8000-000000000001";

/** The one position the tests close: 76 DOGE long. */
function doge(overrides: Parameters<typeof openPosition>[0] = {}) {
  return openPosition({
    allocation_id: ALLOCATION,
    markets: ["DOGEUSDT"],
    base_currency: "DOGE",
    side: "LONG",
    size: "76",
    opened_size: "76",
    ...overrides,
  });
}

type Answer = Response | Promise<Response>;

/** Every request is recorded; a POST to the close route is answered by `answer`. */
function stubFetch(answer: () => Answer = () => jsonResponse({ status: "QUEUED" }, 202)) {
  const calls: Array<{ url: string; method: string }> = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), method: init?.method ?? "GET" });
    return Promise.resolve(answer());
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

function mount(positions = [doge()]) {
  return renderAt(<PositionsTable positions={positions} asOf="2026-11-16T10:00:00Z" currency="USDT" labelledBy="h" variant="pool" />);
}

beforeEach(async () => {
  unlock();
  setViewport("wide");
  await act(() => i18n.changeLanguage("en"));
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

async function settle() {
  for (let turn = 0; turn < 3; turn += 1) await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
}

describe("the confirmation comes first", () => {
  it("opens a dialog naming the symbol and the size, and sends nothing yet", async () => {
    const calls = stubFetch();
    mount();

    fireEvent.click(screen.getByRole("button", { name: "Close now" }));
    await settle();

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("heading").textContent).toContain("DOGEUSDT");
    expect(dialog.textContent).toContain("76 DOGE");
    expect(calls).toEqual([]);
  });

  it("wraps its text and starts each line at the beginning, whatever the right-aligned nowrap cell around it sets (L35)", async () => {
    stubFetch();
    mount();

    fireEvent.click(screen.getByRole("button", { name: "Close now" }));
    await settle();

    expect(screen.getByRole("dialog")).toHaveClass("w-[calc(100%-2rem)]", "max-w-lg", "whitespace-normal", "break-words", "text-left");
  });

  it("sends nothing when cancelled, and the dialog goes", async () => {
    const calls = stubFetch();
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Close now" }));
    await settle();

    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    await settle();

    expect(calls).toEqual([]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("sends exactly one request for that allocation when confirmed, and the dialog goes", async () => {
    const calls = stubFetch();
    mount([doge(), doge({ allocation_id: "bbbbbbbb-0000-4000-8000-000000000002", markets: ["ETHUSDT"] })]);
    fireEvent.click(screen.getAllByRole("button", { name: "Close now" })[0] as HTMLElement);
    await settle();

    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close position" }));
    await settle();

    expect(calls.filter((call) => call.method === "POST")).toEqual([
      { url: expect.stringContaining(`/positions/${ALLOCATION}/close`) as string, method: "POST" },
    ]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("the card of the phone layout has the same button and the same dialog", async () => {
    setViewport("narrow");
    const calls = stubFetch();
    mount();

    fireEvent.click(screen.getByRole("button", { name: "Close now" }));
    await settle();
    expect(screen.getByRole("dialog").textContent).toContain("76 DOGE");
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close position" }));
    await settle();

    expect(calls.filter((call) => call.method === "POST")).toHaveLength(1);
  });
});

describe("what has no button", () => {
  it("a position whose size is not readable has none", () => {
    mount([doge({ size: null })]);

    expect(screen.queryByRole("button", { name: "Close now" })).not.toBeInTheDocument();
  });

  it("a position whose side is not readable has none", () => {
    mount([doge({ side: null })]);

    expect(screen.queryByRole("button", { name: "Close now" })).not.toBeInTheDocument();
  });
});

describe("a refusal", () => {
  it("is written in the dialog, which stays open", async () => {
    stubFetch(() => jsonResponse({ detail: "position not found" }, 404));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Close now" }));
    await settle();

    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close position" }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    expect(screen.getByRole("alert").textContent).toBe("This position is no longer open.");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("any other failure says it could not be sent", async () => {
    stubFetch(() => jsonResponse({}, 500));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Close now" }));
    await settle();

    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close position" }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());

    expect(screen.getByRole("alert").textContent).toBe("The close could not be sent. Try again.");
  });
});

describe("in Spanish", () => {
  it("the button and the dialog are written in the user's language", async () => {
    await act(() => i18n.changeLanguage("es"));
    stubFetch();
    mount();

    fireEvent.click(screen.getByRole("button", { name: "Cerrar ahora" }));
    await settle();

    expect(screen.getByRole("dialog").textContent).toContain("76 DOGE");
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancelar" })).toBeInTheDocument();
  });
});
