import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConfirmBookingDialog } from "@/features/bookings/ConfirmBookingDialog";
import type { BookingProposal } from "@/shared/api/types";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";

function renderWithQueryClient(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const result = render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
  return { ...result, queryClient };
}

function fakeResponse(body: unknown, status: number, ok: boolean = status >= 200 && status < 300): Response {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
  } as Response;
}

const PROPOSAL: BookingProposal = {
  id: "11111111-1111-1111-1111-111111111111",
  discrepancy_id: "22222222-2222-2222-2222-222222222222",
  exchange: "bybit",
  venue: "usdt-m",
  settlement_currency: "USDT",
  symbol: "STXUSDT.P",
  kind: "ATTRIBUTABLE_FULL_CLOSE",
  allocation_id: "33333333-3333-3333-3333-333333333333",
  strategy_id: "44444444-4444-4444-4444-444444444444",
  side: "SELL",
  quantity: "0.100000000000000001",
  observed_venue_net_base: "0",
  observed_ledger_net_base: "-0.1",
  observed_allocation_ids: ["33333333-3333-3333-3333-333333333333"],
  fills: [
    {
      exchange_fill_id: "fill-1",
      exchange_order_id: "order-1",
      side: "SELL",
      quantity: "0.100000000000000001",
      price: "142.37",
      fee: "0.03913",
      fee_currency: "USDT",
      filled_at: "2026-09-23T01:02:03.456000+00:00",
    },
  ],
  client_order_id: "vnu:bybit:order-1",
  expires_at: "2026-09-24T01:02:03+00:00",
  prepared_by_job_id: "55555555-5555-5555-5555-555555555555",
  created_at: "2026-09-23T01:02:03+00:00",
  state: "PENDING",
  decided_at: null,
  decided_by: null,
  decision_reason: null,
  execution_attempt_id: null,
};

describe("ConfirmBookingDialog", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("carries the new confirm-dialog and outcome copy in both locales", () => {
    expect(en.bookings?.dialogs?.confirm?.title).toBeTruthy();
    expect(en.bookings?.dialogs?.confirm?.usdRateNote).toBeTruthy();
    expect(en.bookings?.dialogs?.cancel).toBeTruthy();
    expect(en.bookings?.outcomes?.ALREADY_DECIDED).toBeTruthy();
    expect(en.bookings?.outcomes?.SUPERSEDED).toBeTruthy();
    expect(en.bookings?.outcomes?.EXPIRED).toBeTruthy();
    expect(en.bookings?.outcomes?.DRY_RUN_REFUSED).toBeTruthy();
    expect(en.bookings?.dialogs?.genericError).toBeTruthy();
    expect(es.bookings?.dialogs?.confirm?.title).toBeTruthy();
    expect(es.bookings?.dialogs?.confirm?.usdRateNote).toBeTruthy();
    expect(es.bookings?.dialogs?.cancel).toBeTruthy();
    expect(es.bookings?.outcomes?.ALREADY_DECIDED).toBeTruthy();
    expect(es.bookings?.outcomes?.SUPERSEDED).toBeTruthy();
    expect(es.bookings?.outcomes?.EXPIRED).toBeTruthy();
    expect(es.bookings?.outcomes?.DRY_RUN_REFUSED).toBeTruthy();
    expect(es.bookings?.dialogs?.genericError).toBeTruthy();
  });

  it("renders every fill row and the attempt line from the frozen snapshot, with usd_rate absent", () => {
    vi.stubGlobal("fetch", vi.fn());
    renderWithQueryClient(<ConfirmBookingDialog proposal={PROPOSAL} onClose={vi.fn()} />);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("142.37", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("0.03913", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("#fill-1")).toBeInTheDocument();
    expect(screen.getByText("0.100000000000000001", { exact: false })).toBeInTheDocument();
    expect(screen.getByText(PROPOSAL.client_order_id)).toBeInTheDocument();
    expect(screen.getByText(PROPOSAL.allocation_id)).toBeInTheDocument();
    expect(screen.getByText(PROPOSAL.strategy_id)).toBeInTheDocument();
    expect(screen.getByText(en.bookings.dialogs.confirm.usdRateNote)).toBeInTheDocument();
    expect(screen.queryByText(/usd_rate/i)).not.toBeInTheDocument();
  });

  it("calls the approve mutation only from the confirm button, never from cancel or from opening the dialog", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        fakeResponse({ outcome: "APPROVED", execution_attempt_id: null, ledger_entries_written: 1 }, 200),
      );
    vi.stubGlobal("fetch", fetchMock);
    const onClose = vi.fn();
    renderWithQueryClient(<ConfirmBookingDialog proposal={PROPOSAL} onClose={onClose} />);

    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: en.bookings.dialogs.cancel }));
    expect(onClose).toHaveBeenCalledTimes(1);
    // Flush any pending microtasks/macrotasks a buggy cancel handler might
    // have queued, so this assertion cannot pass merely because the
    // mutation call is asynchronous.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: en.bookings.dialogs.confirm.confirm }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain(`/reconciliation/bookings/${PROPOSAL.id}/approve`);
    expect(init.method).toBe("POST");
  });

  it("disables the confirm button while in flight and sends exactly one request on a double click", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => new Promise(() => {})),
    );
    renderWithQueryClient(<ConfirmBookingDialog proposal={PROPOSAL} onClose={vi.fn()} />);

    const button = screen.getByRole("button", { name: en.bookings.dialogs.confirm.confirm });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1));
    expect(button).toBeDisabled();
  });

  it("shows success only on a 200 and invalidates the pending bookings query", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          fakeResponse({ outcome: "APPROVED", execution_attempt_id: null, ledger_entries_written: 1 }, 200),
        ),
    );
    const { queryClient } = renderWithQueryClient(
      <ConfirmBookingDialog proposal={PROPOSAL} onClose={vi.fn()} />,
    );
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    fireEvent.click(screen.getByRole("button", { name: en.bookings.dialogs.confirm.confirm }));

    expect(await screen.findByText(en.bookings.dialogs.confirm.success)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["bookings", "pending"] });
  });

  it.each([
    ["ALREADY_DECIDED", en.bookings.outcomes.ALREADY_DECIDED],
    ["SUPERSEDED", en.bookings.outcomes.SUPERSEDED],
    ["EXPIRED", en.bookings.outcomes.EXPIRED],
  ])(
    "shows the specific %s outcome on a 409, never success, and still invalidates the query",
    async (outcome, message) => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse({ outcome, detail: "x" }, 409, false)));
      const { queryClient } = renderWithQueryClient(
        <ConfirmBookingDialog proposal={PROPOSAL} onClose={vi.fn()} />,
      );
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

      fireEvent.click(screen.getByRole("button", { name: en.bookings.dialogs.confirm.confirm }));

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(message);
      expect(screen.queryByText(en.bookings.dialogs.confirm.success)).not.toBeInTheDocument();
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["bookings", "pending"] });
    },
  );

  it("shows the DRY_RUN message on a 503, never success, and does not invalidate the query", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(fakeResponse({ outcome: "DRY_RUN_REFUSED", detail: "x" }, 503, false));
    vi.stubGlobal("fetch", fetchMock);
    const { queryClient } = renderWithQueryClient(
      <ConfirmBookingDialog proposal={PROPOSAL} onClose={vi.fn()} />,
    );
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    fireEvent.click(screen.getByRole("button", { name: en.bookings.dialogs.confirm.confirm }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(en.bookings.outcomes.DRY_RUN_REFUSED);
    expect(screen.queryByText(en.bookings.dialogs.confirm.success)).not.toBeInTheDocument();
    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("shows a generic error on a 404, never success or a specific outcome text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(fakeResponse({ detail: "no such booking proposal" }, 404, false)),
    );
    renderWithQueryClient(<ConfirmBookingDialog proposal={PROPOSAL} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: en.bookings.dialogs.confirm.confirm }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(en.bookings.dialogs.genericError);
  });

  it("shows a generic error on a network failure, never success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    renderWithQueryClient(<ConfirmBookingDialog proposal={PROPOSAL} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: en.bookings.dialogs.confirm.confirm }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(en.bookings.dialogs.genericError);
    expect(screen.queryByText(en.bookings.dialogs.confirm.success)).not.toBeInTheDocument();
  });
});
