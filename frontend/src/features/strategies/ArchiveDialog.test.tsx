import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ArchiveControl } from "@/features/strategies/ArchiveControl";
import { ArchiveDialog } from "@/features/strategies/ArchiveDialog";
import { ApiError } from "@/shared/api/client";
import { API_BASE_URL } from "@/shared/api/config";
import type { Strategy } from "@/shared/api/types";
import { useTokenStore } from "@/shared/auth/token-store";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { jsonResponse } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const NAME = "ETH Breakout";
const REF_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const REF_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

const KEYS = [
  "button",
  "cancel",
  "confirm",
  "confirmBody",
  "confirmTitle",
  "description",
  "disabledHint",
  "errors.generic",
  "errors.openPosition",
  "errors.stillEnabled",
  "pending",
  "reasons.allocations_one",
  "reasons.allocations_other",
  "reasons.inFlightAttempts_one",
  "reasons.inFlightAttempts_other",
  "reasons.liveReservations_one",
  "reasons.liveReservations_other",
  "reasons.symbols",
  "title",
];

function flatten(node: unknown, prefix = ""): string[] {
  if (typeof node === "string") return [prefix];
  if (typeof node !== "object" || node === null) return [];
  return Object.entries(node).flatMap(([key, value]) => flatten(value, prefix ? `${prefix}.${key}` : key));
}

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

function refusal(code: string, extra: Record<string, unknown> = {}) {
  return new ApiError(409, { detail: { error: code, message: "server text", ...extra } });
}

const OPEN_POSITION = {
  symbols: ["ETHUSDT", "SOLUSDT"],
  allocations: [REF_A, REF_B],
  live_reservations: [REF_A],
  in_flight_attempts: [REF_B],
};

function renderDialog(props: Partial<Parameters<typeof ArchiveDialog>[0]> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(<ArchiveDialog name={NAME} pending={false} error={null} onConfirm={onConfirm} onCancel={onCancel} {...props} />);
  return { onConfirm, onCancel };
}

function renderControl(subject: Strategy = strategy()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ArchiveControl strategy={subject} />
    </QueryClientProvider>,
  );
}

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  useTokenStore.setState({ token: "a-token" });
});
afterEach(async () => {
  vi.unstubAllGlobals();
  useTokenStore.setState({ token: null });
  await i18n.changeLanguage("en");
});

describe("ArchiveControl", () => {
  it("test_archive_requires_explicit_confirmation_not_single_click", async () => {
    const fetchMock = stubFetch(jsonResponse(strategy({ archived_at: "2026-10-03T00:00:00+00:00" })));
    renderControl();
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.archive.button") }));

    expect(screen.getByRole("dialog", { name: i18n.t("strategies.archive.confirmTitle", { name: NAME }) })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.archive.confirm") }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const call = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(call[0]).toBe(`${API_BASE_URL}/api/strategies/${ID}/archive`);
    expect(call[1].method).toBe("POST");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("cancelling the confirmation sends nothing", () => {
    const fetchMock = stubFetch(jsonResponse(strategy()));
    renderControl();

    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.archive.button") }));
    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.archive.cancel") }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("is unavailable while the strategy is enabled and says it must be disabled and flat first", () => {
    renderControl(strategy({ enabled: true }));
    const button = screen.getByRole("button", { name: i18n.t("strategies.archive.button") });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription(i18n.t("strategies.archive.disabledHint"));
    fireEvent.click(button);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("is not offered for a strategy that is already archived", () => {
    renderControl(strategy({ archived_at: "2026-09-01T00:00:00+00:00" }));
    expect(screen.queryByRole("button", { name: i18n.t("strategies.archive.button") })).toBeNull();
    expect(screen.queryByText(i18n.t("strategies.archive.disabledHint"))).toBeNull();
  });

  it("keeps the dialog open with the refusal when the server refuses", async () => {
    stubFetch(jsonResponse({ detail: { error: "OPEN_POSITION", message: "open", ...OPEN_POSITION } }, 409));
    renderControl();

    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.archive.button") }));
    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.archive.confirm") }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(i18n.t("strategies.archive.reasons.symbols", { symbols: "ETHUSDT, SOLUSDT" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("clears the refusal when the dialog is cancelled and opened again", async () => {
    stubFetch(jsonResponse({ detail: { error: "STILL_ENABLED", message: "m" } }, 409));
    renderControl();
    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.archive.button") }));
    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.archive.confirm") }));
    await screen.findByRole("alert");

    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.archive.cancel") }));
    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.archive.button") }));

    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("ArchiveDialog", () => {
  it("test_409_open_position_reasons_rendered_symbols_allocations_reservations_attempts", () => {
    renderDialog({ error: refusal("OPEN_POSITION", OPEN_POSITION) });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(i18n.t("strategies.archive.errors.openPosition"));
    const items = within(alert).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      i18n.t("strategies.archive.reasons.symbols", { symbols: "ETHUSDT, SOLUSDT" }),
      i18n.t("strategies.archive.reasons.allocations", { count: 2 }),
      i18n.t("strategies.archive.reasons.liveReservations", { count: 1 }),
      i18n.t("strategies.archive.reasons.inFlightAttempts", { count: 1 }),
    ]);
    expect(items.map((item) => item.textContent)).toEqual([
      "Open position on: ETHUSDT, SOLUSDT",
      "2 open allocations",
      "1 live reservation",
      "1 execution attempt in flight",
    ]);
  });

  it("names only the reasons that exist", () => {
    renderDialog({ error: refusal("OPEN_POSITION", { ...OPEN_POSITION, symbols: [], allocations: [], live_reservations: [] }) });

    const items = within(screen.getByRole("alert")).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([i18n.t("strategies.archive.reasons.inFlightAttempts", { count: 1 })]);
  });

  it.each([
    ["missing", undefined],
    ["not a list", "ETHUSDT"],
    ["a list with a non-string", ["ETHUSDT", 7]],
  ])("shows the main sentence alone when the symbols are %s", (_label, symbols) => {
    renderDialog({ error: refusal("OPEN_POSITION", { ...OPEN_POSITION, symbols }) });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(i18n.t("strategies.archive.errors.openPosition"));
    expect(within(alert).queryAllByRole("listitem")).toHaveLength(0);
  });

  it("test_409_still_enabled_rendered", () => {
    renderDialog({ error: refusal("STILL_ENABLED") });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(i18n.t("strategies.archive.errors.stillEnabled"));
    expect(within(alert).queryAllByRole("listitem")).toHaveLength(0);
  });

  it("renders the generic refusal for any other error", () => {
    renderDialog({ error: new Error("boom") });
    expect(screen.getByRole("alert")).toHaveTextContent(i18n.t("strategies.archive.errors.generic"));
  });

  it("states what archiving does and names the strategy", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog", { name: i18n.t("strategies.archive.confirmTitle", { name: NAME }) });
    expect(dialog).toHaveTextContent(i18n.t("strategies.archive.confirmBody", { name: NAME }));
    expect(i18n.t("strategies.archive.confirmBody", { name: NAME })).toMatch(/cannot be enabled or restored/);
  });

  it("confirms only on the confirm button, and cancel, Escape and a cancel event never confirm", () => {
    const { onConfirm, onCancel } = renderDialog();
    const dialog = screen.getByRole("dialog");

    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.archive.cancel") }));
    fireEvent.keyDown(dialog, { key: "Escape" });
    fireEvent(dialog, new Event("cancel", { cancelable: true }));
    expect(onCancel).toHaveBeenCalledTimes(3);
    expect(onConfirm).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.archive.confirm") }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("disables both buttons and ignores Escape while the archive is in flight", () => {
    const { onCancel } = renderDialog({ pending: true });
    expect(screen.getByRole("button", { name: i18n.t("strategies.archive.pending") })).toBeDisabled();
    expect(screen.getByRole("button", { name: i18n.t("strategies.archive.cancel") })).toBeDisabled();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("renders its texts in Spanish", async () => {
    await i18n.changeLanguage("es");
    renderDialog({ error: refusal("OPEN_POSITION", OPEN_POSITION) });
    expect(screen.getByRole("dialog", { name: es.strategies.archive.confirmTitle.replace("{{name}}", NAME) })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(es.strategies.archive.errors.openPosition);
    expect(screen.getByRole("alert")).toHaveTextContent("ETHUSDT, SOLUSDT");
  });

  it("has every key in en and es", () => {
    expect(flatten(en.strategies.archive).sort()).toEqual(KEYS);
    expect(flatten(es.strategies.archive).sort()).toEqual(KEYS);
  });
});
