import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigationType } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DeleteStrategyControl } from "@/features/strategies/DeleteStrategyControl";
import { API_BASE_URL } from "@/shared/api/config";
import type { Strategy } from "@/shared/api/types";
import { useTokenStore } from "@/shared/auth/token-store";
import i18n from "@/shared/i18n";
import es from "@/shared/i18n/locales/es.json";
import { jsonResponse } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const NAME = "ETH Breakout";
const NO_CONTENT = { ok: true, status: 204, json: () => Promise.reject(new Error("no body")) } as Response;

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: ID,
    name: NAME,
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    allocation_percent: "100",
    enabled: false,
    archived_at: null,
    allowed_pairs: ["ETHUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    ...overrides,
  };
}

function ListPage() {
  return <p>list page via {useNavigationType()}</p>;
}

function renderControl(subject: Strategy = strategy()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/strategies/${ID}`]}>
        <Routes>
          <Route path="strategies" element={<ListPage />} />
          <Route path="strategies/:strategyId" element={<DeleteStrategyControl strategy={subject} />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function openAndConfirm() {
  fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.delete.button") }));
  fireEvent.change(screen.getByLabelText(i18n.t("strategies.delete.typeName")), { target: { value: NAME } });
  fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.delete.confirm") }));
}

beforeEach(() => {
  useTokenStore.setState({ token: "a-token" });
});
afterEach(async () => {
  vi.unstubAllGlobals();
  useTokenStore.setState({ token: null });
  await i18n.changeLanguage("en");
});

describe("DeleteStrategyControl", () => {
  it("opens the confirmation on a single click and sends no request", () => {
    const fetchMock = stubFetch(NO_CONTENT);
    renderControl();
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.delete.button") }));

    expect(screen.getByRole("dialog", { name: i18n.t("strategies.delete.confirmTitle", { name: NAME }) })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("disables the button with a hint while the strategy is enabled", () => {
    renderControl(strategy({ enabled: true }));
    const button = screen.getByRole("button", { name: i18n.t("strategies.delete.button") });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription(i18n.t("strategies.delete.disabledHint"));
    fireEvent.click(button);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("offers the control for an archived strategy", () => {
    renderControl(strategy({ archived_at: "2026-09-01T00:00:00+00:00" }));
    expect(screen.getByRole("button", { name: i18n.t("strategies.delete.button") })).toBeEnabled();
    expect(screen.queryByText(i18n.t("strategies.delete.disabledHint"))).toBeNull();
  });

  it("sends the request and navigates to the list with replace after a confirmed delete", async () => {
    const fetchMock = stubFetch(NO_CONTENT);
    renderControl();

    openAndConfirm();

    expect(await screen.findByText("list page via REPLACE")).toBeInTheDocument();
    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(call[0]).toBe(`${API_BASE_URL}/api/strategies/${ID}`);
    expect(call[1].method).toBe("DELETE");
  });

  it("navigates to the list without an error on a 404", async () => {
    stubFetch(jsonResponse({ detail: "no strategy" }, 404));
    renderControl();

    openAndConfirm();

    expect(await screen.findByText("list page via REPLACE")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the dialog open with the refusal and does not navigate on a 409", async () => {
    const history = { signals: 3, reservations: 0, execution_attempts: 0, ledger_entries: 0, booking_proposals: 0, enablement_events: 0 };
    stubFetch(jsonResponse({ detail: { error: "HAS_HISTORY", message: "m", history } }, 409));
    renderControl();

    openAndConfirm();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(i18n.t("strategies.delete.history.signals", { count: 3 }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByText(/list page via/)).toBeNull();
    expect(screen.getByRole("button", { name: i18n.t("strategies.delete.confirm") })).toBeEnabled();
  });

  it("clears the refusal when the dialog is cancelled and opened again", async () => {
    stubFetch(jsonResponse({ detail: { error: "STILL_ENABLED", message: "m" } }, 409));
    renderControl();
    openAndConfirm();
    await screen.findByRole("alert");

    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.delete.cancel") }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.delete.button") }));

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByLabelText(i18n.t("strategies.delete.typeName"))).toHaveValue("");
  });

  it("renders its texts in Spanish", async () => {
    await i18n.changeLanguage("es");
    renderControl();
    expect(screen.getByRole("heading", { name: es.strategies.delete.title })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: es.strategies.delete.button }));
    expect(screen.getByRole("dialog", { name: es.strategies.delete.confirmTitle.replace("{{name}}", NAME) })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: es.strategies.delete.confirm })).toBeDisabled());
  });
});
