import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StrategyDetailPage } from "@/features/strategies/StrategyDetailPage";
import type { EnablementEvent, Strategy } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { useExchangeStore } from "@/shared/scope/exchange-store";
import { jsonResponse, lock, pool, renderAt, resetExchangeScope, stubApi, unlock } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const DAY = 86_400;
const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: ID,
    name: "ETH Breakout",
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

interface Options {
  events?: EnablementEvent[];
  pools?: unknown[];
  strategyAnswer?: () => Response;
  patch?: (body: unknown) => Response;
}

function renderPage(subject: Strategy = strategy(), options: Options = {}) {
  const requests: Array<{ method: string; url: string }> = [];
  stubApi(
    HEALTH,
    [],
    { kind: "ok", body: options.pools ?? [pool("bybit", "usdt-m")] },
    {},
    (url, init) => {
      const method = init?.method ?? "GET";
      if (!url.includes(`/strategies/${ID}`)) return undefined;
      requests.push({ method, url });
      if (url.endsWith("/events")) return Promise.resolve(jsonResponse(options.events ?? []));
      if (method === "PATCH") return Promise.resolve(options.patch?.(JSON.parse(String(init?.body))) ?? jsonResponse(subject));
      return Promise.resolve(options.strategyAnswer?.() ?? jsonResponse(subject));
    },
  );
  renderAt(
    <Routes>
      <Route path="strategies" element={<p>the list</p>} />
      <Route path="strategies/:strategyId" element={<StrategyDetailPage />} />
    </Routes>,
    `/strategies/${ID}`,
  );
  return requests;
}

const heading = (name: string) => screen.findByRole("heading", { level: 1, name });

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

describe("StrategyDetailPage", () => {
  it("test_shows_active_x_days_since_first_activation_date", async () => {
    renderPage(
      strategy({ enabled: true, uptime: { seconds: 10 * DAY + 3_600, first_enabled_at: "2026-08-12T10:00:00+00:00", baseline: false } }),
    );

    await heading("ETH Breakout");

    expect(screen.getByText("active 10 days since Aug 12, 2026")).toBeInTheDocument();
  });

  it("says 'at least' when the first activation was written by a migration baseline", async () => {
    renderPage(
      strategy({ enabled: true, uptime: { seconds: 1 * DAY, first_enabled_at: "2026-08-12T10:00:00+00:00", baseline: true } }),
    );

    await heading("ETH Breakout");

    expect(screen.getByText("active at least 1 day, since at least Aug 12, 2026")).toBeInTheDocument();
  });

  it("test_never_enabled_shows_no_activation_date", async () => {
    renderPage(strategy());

    await heading("ETH Breakout");

    expect(screen.getByText(i18n.t("strategies.row.neverEnabled"))).toBeInTheDocument();
    expect(screen.queryByText(/since/)).toBeNull();
  });

  it("test_the_delete_control_is_rendered_below_the_archive_control_for_the_loaded_strategy", async () => {
    renderPage();
    await heading("ETH Breakout");

    const archive = screen.getByRole("button", { name: i18n.t("strategies.archive.button") });
    const remove = screen.getByRole("button", { name: i18n.t("strategies.delete.button") });
    expect(archive.compareDocumentPosition(remove) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    fireEvent.click(remove);
    expect(screen.getByRole("dialog", { name: i18n.t("strategies.delete.confirmTitle", { name: "ETH Breakout" }) })).toBeInTheDocument();
  });

  it("mounts the allowed-pairs editor on the strategy's own pairs", async () => {
    renderPage(strategy({ allowed_pairs: ["ETHUSDT", "SOLUSDT"] }));
    await heading("ETH Breakout");

    const chips = screen.getByRole("list", { name: i18n.t("strategies.pairs.selected") });
    expect(within(chips).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["ETHUSDT×", "SOLUSDT×"]);
  });

  it("says the strategy does not exist on a 404, and links back to the list", async () => {
    renderPage(strategy(), { strategyAnswer: () => jsonResponse({ detail: "no strategy" }, 404) });

    expect(await screen.findByText(i18n.t("strategies.detail.notFound"))).toBeInTheDocument();
    expect(screen.getByRole("link", { name: i18n.t("strategies.detail.back") })).toHaveAttribute("href", "/strategies");
    expect(screen.queryByRole("button", { name: i18n.t("strategies.delete.button") })).toBeNull();
  });

  it("says the strategy could not be loaded when the body is not a strategy", async () => {
    renderPage(strategy(), { strategyAnswer: () => jsonResponse({ id: ID }) });

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.detail.error"));
    expect(screen.queryByRole("button", { name: i18n.t("strategies.archive.button") })).toBeNull();
  });

  it("scopes the exchange tabs to the strategy's exchange", async () => {
    useExchangeStore.setState({ selected: "binance" });
    renderPage(strategy(), { pools: [pool("binance", "usdt-m"), pool("bybit", "usdt-m")] });
    await heading("ETH Breakout");

    await waitFor(() => expect(useExchangeStore.getState().selected).toBe("bybit"));
  });

  it("leaves the exchange tabs alone when the strategy's exchange has no pool", async () => {
    useExchangeStore.setState({ selected: "bybit" });
    renderPage(strategy({ exchange: "pionex" }), { pools: [pool("bybit", "usdt-m")] });
    await heading("ETH Breakout");

    expect(useExchangeStore.getState().selected).toBe("bybit");
  });

  it("enables and disables through PATCH and says when the change was refused", async () => {
    const bodies: unknown[] = [];
    renderPage(strategy({ enabled: true }), {
      patch: (body) => {
        bodies.push(body);
        return jsonResponse({ detail: "no" }, 409);
      },
    });
    await heading("ETH Breakout");

    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.detail.disable") }));

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.row.toggleError"));
    expect(bodies).toEqual([{ enabled: false }]);
  });

  it("is read-only once archived: status shown, nothing to enable or archive", async () => {
    renderPage(strategy({ archived_at: "2026-09-01T00:00:00+00:00" }));
    await heading("ETH Breakout");

    expect(screen.getByText(i18n.t("strategies.row.archived"))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: i18n.t("strategies.detail.enable") })).toBeDisabled();
    expect(screen.queryByRole("button", { name: i18n.t("strategies.archive.button") })).toBeNull();
  });

  it("lists the enable history newest first and marks a baseline row", async () => {
    renderPage(strategy({ enabled: true }), {
      events: [
        { enabled: true, occurred_at: "2026-08-01T10:00:00+00:00", origin: "BASELINE" },
        { enabled: false, occurred_at: "2026-08-10T10:00:00+00:00", origin: "OBSERVED" },
        { enabled: true, occurred_at: "2026-08-12T10:00:00+00:00", origin: "OBSERVED" },
      ],
    });
    await heading("ETH Breakout");

    const history = await screen.findByRole("list", { name: i18n.t("strategies.detail.history.title") });
    const rows = within(history).getAllByRole("listitem").map((item) => item.textContent);
    expect(rows).toEqual([
      "Enabled · Aug 12, 2026",
      "Disabled · Aug 10, 2026",
      `Enabled · Aug 1, 2026 · ${i18n.t("strategies.detail.history.baseline")}`,
    ]);
  });

  it("test_the_history_list_has_a_fixed_max_height_scrolls_and_is_keyboard_reachable", async () => {
    renderPage(strategy(), { events: [{ enabled: true, occurred_at: "2026-08-12T10:00:00+00:00", origin: "OBSERVED" }] });
    await heading("ETH Breakout");

    const history = await screen.findByRole("list", { name: i18n.t("strategies.detail.history.title") });
    expect(history).toHaveClass("max-h-100", "overflow-y-auto");
    expect(history).toHaveAttribute("tabindex", "0");
    expect(history).not.toHaveClass("h-100");
  });

  it("says so when nothing was ever enabled or disabled", async () => {
    renderPage();
    expect(await screen.findByText(i18n.t("strategies.detail.history.empty"))).toBeInTheDocument();
  });

  it("says the history could not be read when its body is malformed, and the rest of the page still works", async () => {
    renderPage(strategy(), { events: [{ enabled: "yes" }] as unknown as EnablementEvent[] });

    expect(await screen.findByText(i18n.t("strategies.detail.history.error"))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: i18n.t("strategies.archive.button") })).toBeEnabled();
  });

  it("shows the webhook message of the loaded strategy, with its id as signal_type, above the delete control", async () => {
    renderPage();
    await heading("ETH Breakout");

    const message = screen.getByRole("group", { name: en.strategies.webhook.messageLabel });
    expect(JSON.parse(message.textContent ?? "")).toMatchObject({ signal_type: ID });
    expect(screen.getByText(`/webhook/tradingview?secret=${en.strategies.webhook.secretPlaceholder}`)).toBeInTheDocument();
    const deleteButton = screen.getByRole("button", { name: i18n.t("strategies.delete.button") });
    expect(message.compareDocumentPosition(deleteButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("renders in Spanish and has the same keys in both locales", async () => {
    await i18n.changeLanguage("es");
    renderPage(strategy({ uptime: { seconds: 2 * DAY, first_enabled_at: "2026-08-12T10:00:00+00:00", baseline: false } }));

    expect(await screen.findByRole("link", { name: es.strategies.detail.back })).toBeInTheDocument();
    expect(screen.getByText("activa 2 días desde el 12 ago 2026")).toBeInTheDocument();

    const keys = (node: unknown, prefix = ""): string[] =>
      typeof node === "object" && node !== null
        ? Object.entries(node).flatMap(([key, value]) => keys(value, `${prefix}${key}.`))
        : [prefix];
    expect(keys(es.strategies).sort()).toEqual(keys(en.strategies).sort());
  });
});
