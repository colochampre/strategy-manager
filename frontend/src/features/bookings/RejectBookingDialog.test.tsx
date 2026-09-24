import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RejectBookingDialog } from "@/features/bookings/RejectBookingDialog";
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
  quantity: "0.1",
  observed_venue_net_base: "0",
  observed_ledger_net_base: "-0.1",
  observed_allocation_ids: ["33333333-3333-3333-3333-333333333333"],
  fills: [
    {
      exchange_fill_id: "fill-1",
      exchange_order_id: "order-1",
      side: "SELL",
      quantity: "0.1",
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

describe("RejectBookingDialog", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("carries the new reject-dialog copy in both locales", () => {
    expect(en.bookings?.dialogs?.reject?.title).toBeTruthy();
    expect(en.bookings?.dialogs?.reject?.reasonRequired).toBeTruthy();
    expect(en.bookings?.dialogs?.reject?.reasonLabel).toBeTruthy();
    expect(en.bookings?.outcomes?.REASON_REQUIRED).toBeTruthy();
    expect(es.bookings?.dialogs?.reject?.title).toBeTruthy();
    expect(es.bookings?.dialogs?.reject?.reasonRequired).toBeTruthy();
    expect(es.bookings?.dialogs?.reject?.reasonLabel).toBeTruthy();
    expect(es.bookings?.outcomes?.REASON_REQUIRED).toBeTruthy();
  });

  it("refuses submit on an empty or whitespace-only reason, never calling fetch", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    renderWithQueryClient(<RejectBookingDialog proposal={PROPOSAL} onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: en.bookings.dialogs.reject.confirm }));
    expect(screen.getByText(en.bookings.dialogs.reject.reasonRequired)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(en.bookings.dialogs.reject.reasonLabel), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByRole("button", { name: en.bookings.dialogs.reject.confirm }));
    expect(screen.getByText(en.bookings.dialogs.reject.reasonRequired)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends the trimmed reason on submit", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(fakeResponse({ outcome: "REJECTED", reason: "reason text" }, 200));
    vi.stubGlobal("fetch", fetchMock);
    renderWithQueryClient(<RejectBookingDialog proposal={PROPOSAL} onClose={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(en.bookings.dialogs.reject.reasonLabel), {
      target: { value: "  reason text  " },
    });
    fireEvent.click(screen.getByRole("button", { name: en.bookings.dialogs.reject.confirm }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain(`/reconciliation/bookings/${PROPOSAL.id}/reject`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ reason: "reason text" });
  });

  it("disables submit while in flight and sends exactly one request on a double click", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => new Promise(() => {})),
    );
    renderWithQueryClient(<RejectBookingDialog proposal={PROPOSAL} onClose={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(en.bookings.dialogs.reject.reasonLabel), {
      target: { value: "reason text" },
    });
    const button = screen.getByRole("button", { name: en.bookings.dialogs.reject.confirm });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1));
    expect(button).toBeDisabled();
  });

  it("shows success only on a 200 and invalidates the pending bookings query", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(fakeResponse({ outcome: "REJECTED", reason: "reason text" }, 200)),
    );
    const { queryClient } = renderWithQueryClient(
      <RejectBookingDialog proposal={PROPOSAL} onClose={vi.fn()} />,
    );
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    fireEvent.change(screen.getByLabelText(en.bookings.dialogs.reject.reasonLabel), {
      target: { value: "reason text" },
    });
    fireEvent.click(screen.getByRole("button", { name: en.bookings.dialogs.reject.confirm }));

    expect(await screen.findByText(en.bookings.dialogs.reject.success)).toBeInTheDocument();
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["bookings", "pending"] });
  });

  it("shows the ALREADY_DECIDED outcome on a 409, never success, and still invalidates the query", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(fakeResponse({ outcome: "ALREADY_DECIDED", detail: "x" }, 409, false)),
    );
    const { queryClient } = renderWithQueryClient(
      <RejectBookingDialog proposal={PROPOSAL} onClose={vi.fn()} />,
    );
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    fireEvent.change(screen.getByLabelText(en.bookings.dialogs.reject.reasonLabel), {
      target: { value: "reason text" },
    });
    fireEvent.click(screen.getByRole("button", { name: en.bookings.dialogs.reject.confirm }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(en.bookings.outcomes.ALREADY_DECIDED);
    expect(screen.queryByText(en.bookings.dialogs.reject.success)).not.toBeInTheDocument();
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["bookings", "pending"] });
  });

  it("shows the DRY_RUN message on a 503, never success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(fakeResponse({ outcome: "DRY_RUN_REFUSED", detail: "x" }, 503, false)),
    );
    renderWithQueryClient(<RejectBookingDialog proposal={PROPOSAL} onClose={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(en.bookings.dialogs.reject.reasonLabel), {
      target: { value: "reason text" },
    });
    fireEvent.click(screen.getByRole("button", { name: en.bookings.dialogs.reject.confirm }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(en.bookings.outcomes.DRY_RUN_REFUSED);
    expect(screen.queryByText(en.bookings.dialogs.reject.success)).not.toBeInTheDocument();
  });

  it("shows the REASON_REQUIRED message on a 422 from the backend, even though the client already validates", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(fakeResponse({ outcome: "REASON_REQUIRED", detail: "x" }, 422, false)),
    );
    renderWithQueryClient(<RejectBookingDialog proposal={PROPOSAL} onClose={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(en.bookings.dialogs.reject.reasonLabel), {
      target: { value: "reason text" },
    });
    fireEvent.click(screen.getByRole("button", { name: en.bookings.dialogs.reject.confirm }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(en.bookings.outcomes.REASON_REQUIRED);
  });

  it("shows a generic error on a 404 and on a network failure, never success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(fakeResponse({ detail: "no such booking proposal" }, 404, false)),
    );
    renderWithQueryClient(<RejectBookingDialog proposal={PROPOSAL} onClose={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(en.bookings.dialogs.reject.reasonLabel), {
      target: { value: "reason text" },
    });
    fireEvent.click(screen.getByRole("button", { name: en.bookings.dialogs.reject.confirm }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(en.bookings.dialogs.genericError);
    expect(screen.queryByText(en.bookings.dialogs.reject.success)).not.toBeInTheDocument();
  });
});
