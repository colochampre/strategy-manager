import { screen, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import { StrategyDetailPage } from "@/features/strategies/StrategyDetailPage";
import type { Strategy } from "@/shared/api/types";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import {
  emptyPerformance,
  heldSubscription,
  jsonResponse,
  lock,
  pool,
  publicRecord,
  publicStrategy,
  renderAt,
  resetExchangeScope,
  setViewport,
  SIGNED_UP,
  stubApi,
  subscriptionOf,
  unlock,
  unsyncedSharePreview,
} from "@/test/harness";

/**
 * The aside of both strategy pages as the approved prototype draws them (RD.7e, S16, `ex11` and `ex12`): the
 * rules are the field boxes, their unit, the confirm buttons, the labels, the chips, the hint lines and the
 * row of buttons. The behaviour of each control has its own tests beside it; these read only the look.
 */
const ID = "11111111-1111-4111-8111-111111111111";

function strategy(overrides: Partial<Strategy> = {}): Strategy {
  return {
    id: ID,
    name: "ETH Breakout",
    exchange: "bybit",
    venue: "usdt-m",
    settlement_currency: "USDT",
    fill_mode: "SKIP",
    subscription: subscriptionOf(ID, "15", { leverage: 2 }),
    enabled: false,
    archived_at: null,
    allowed_pairs: ["ETHUSDT", "BTCUSDT"],
    uptime: { seconds: 0, first_enabled_at: null, baseline: false },
    visibility: "LINK",
    share_token: "k7QmX2",
    secret_last4: "x4F2",
    description: null,
    subscribers: 1,
    live_subscribers: 0,
    created_at: null,
    capital: null,
    stop_loss_pct: "10.00",
    ...overrides,
  };
}

function renderOwn(subject: Strategy = strategy()) {
  stubApi({ kind: "ok", body: { status: "ok", dry_run: true } }, [], { kind: "ok", body: [pool("bybit", "usdt-m")] }, {}, (url) => {
    if (url.includes(`/performance/strategies/${ID}/trades`)) return Promise.resolve(jsonResponse({ trades: [], next_cursor: null }));
    if (url.endsWith(`/performance/strategies/${ID}`)) {
      return Promise.resolve(
        jsonResponse({ ...emptyPerformance("bybit", "usdt-m", "USDT"), strategy_id: ID, by_pair: [] }),
      );
    }
    if (!url.includes(`/strategies/${ID}`)) return undefined;
    if (url.includes("/share-preview")) return Promise.resolve(jsonResponse(unsyncedSharePreview(ID)));
    if (url.endsWith("/events")) {
      return Promise.resolve(
        jsonResponse([{ enabled: true, occurred_at: "2026-08-12T10:00:00+00:00", origin: "OBSERVED" }]),
      );
    }
    return Promise.resolve(jsonResponse(subject));
  });
  renderAt(
    <Routes>
      <Route path="strategies/:strategyId" element={<StrategyDetailPage />} />
    </Routes>,
    `/strategies/${ID}`,
  );
}

const settings = () => screen.getByRole("complementary", { name: en.strategies.detail.settings });

async function openOwn(subject?: Strategy) {
  renderOwn(subject);
  await screen.findByRole("heading", { level: 1, name: "ETH Breakout" });
  await screen.findByRole("textbox", { name: en.strategies.detail.share.label });
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
  setViewport("wide");
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

describe("the aside of an own strategy (ex12)", () => {
  it("draws each field as a 38 px box with its unit inside, at the far end", async () => {
    await openOwn();
    const fields = [
      [en.strategies.detail.share.label, "%"],
      [en.strategies.leverage.label, "x"],
      [en.strategies.stopLevel.label, en.strategies.stopLevel.unit],
    ] as const;
    for (const [name, unit] of fields) {
      const input = within(settings()).getByRole("textbox", { name });
      const box = input.parentElement as HTMLElement;
      expect(box).toHaveClass("h-9.5", "rounded-lg", "bg-ground", "border-rule");
      // The number takes the room the unit leaves, so the unit sits at the end of the box.
      expect(input).toHaveClass("flex-1");
      const mark = within(box).getByText(unit);
      expect(mark).toHaveClass("text-ink-3");
      expect(box.lastElementChild).toBe(mark);
    }
  });

  it("confirms each field with a 36 px check button beside it, in the neutral look", async () => {
    await openOwn();
    const saves = within(settings()).getAllByRole("button", { name: en.strategies.detail.share.save });
    // The share, the leverage, the stop level and the allowed pairs.
    expect(saves).toHaveLength(4);
    for (const save of saves) {
      expect(save).toHaveClass("size-9", "rounded-lg", "border-rule", "bg-panel", "text-ink-2");
      expect(save).not.toHaveClass("bg-gain");
      expect(save.querySelector("svg.lucide-check")).not.toBeNull();
    }
    const copy = within(settings()).getByRole("button", { name: en.strategies.sharing.copyLink });
    expect(copy).toHaveClass("size-9", "rounded-lg", "border-rule", "bg-panel");
    expect(settings().querySelector("input[readonly]")).toHaveClass("h-9.5", "rounded-lg", "bg-ground");
  });

  it("names the link, the stop level and the pairs in small bold type, and the share and leverage in plain", async () => {
    await openOwn();
    const link = within(settings()).getByRole("heading", { name: en.strategies.sharing.linkTitle });
    expect(link).toHaveClass("text-xs", "font-semibold");
    const stop = within(settings()).getByText(en.strategies.stopLevel.label, { selector: "label" });
    expect(stop).toHaveClass("text-xs", "font-semibold");
    const pairs = within(settings()).getByText(en.strategies.detail.pairs.title, { selector: "span" });
    expect(pairs).toHaveClass("text-xs", "font-semibold");
    for (const text of [en.strategies.detail.share.label, en.strategies.leverage.label]) {
      expect(within(settings()).getByText(text, { selector: "label" })).toHaveClass("text-sm");
    }
  });

  it("keeps the leverage's cap line under its field as a small, quiet hint", async () => {
    await openOwn();
    // The cap line stays right under the leverage field (owner, 2026-11-17), as a hint.
    expect(within(settings()).getByText("Max leverage x9 with a 10% stop")).toHaveClass("text-xs", "text-ink-3");
  });

  it("draws the allowed pairs as chips on their own row, with a search icon at the end of the search field", async () => {
    await openOwn();
    const chips = within(settings()).getByRole("list", { name: en.strategies.pairs.selected });
    const name = within(settings()).getByText(en.strategies.detail.pairs.title, { selector: "span" });
    expect(chips.parentElement).not.toBe(name.parentElement);
    for (const chip of within(chips).getAllByRole("listitem")) {
      expect(chip).toHaveClass("h-6.5", "rounded-full", "border-rule", "bg-ground", "text-xs", "text-ink-2");
    }
    expect(within(chips).getByText("ETHUSDT")).toHaveClass("font-medium", "text-ink");
    const search = within(settings()).getByRole("searchbox", { name: en.strategies.pairs.search });
    expect(search.parentElement?.querySelector("svg.lucide-search")).not.toBeNull();
    expect(search).toHaveClass("h-9.5", "rounded-lg", "bg-ground");
  });

  it("sets Disable wider than Archive and draws it on the raised background", async () => {
    await openOwn();
    const disable = within(settings()).getByRole("button", { name: en.strategies.detail.enable });
    const archive = within(settings()).getByRole("button", { name: en.strategies.archive.button });
    expect(disable.parentElement).toHaveClass("flex-1", "grow-[1.6]");
    expect(archive.parentElement).not.toHaveClass("grow-[1.6]");
    expect(disable).toHaveClass("bg-panel-2", "border-rule-strong", "rounded-lg");
  });

  it("shows the visibility as a 38 px box of at least 132 px", async () => {
    await openOwn();
    const select = within(settings()).getByRole("combobox", { name: en.strategies.visibility.label });
    expect(select).toHaveClass("h-9.5", "rounded-lg", "bg-ground", "border-rule");
    expect(select.parentElement?.parentElement?.parentElement).toHaveClass("min-w-33");
  });

  it("titles the history in 15 px type", async () => {
    await openOwn();
    const heading = await within(settings()).findByRole("heading", { name: en.strategies.detail.history.title });
    expect(heading).toHaveClass("text-[15px]");
  });
});

/** The reader of another author's strategy: not the author, with a pool that serves its market. */
function serve(held: unknown[] = []) {
  return stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [pool("bybit")] }, {}, (url, init) => {
    if (url.endsWith(`/api/public/strategies/${ID}`)) return Promise.resolve(jsonResponse(publicStrategy({ id: ID })));
    if (url.endsWith(`/api/public/strategies/${ID}/record`)) return Promise.resolve(jsonResponse(publicRecord()));
    if (url.includes(`/api/performance/strategies/${ID}`)) {
      return Promise.resolve(
        jsonResponse({ ...emptyPerformance("bybit", "usdt-m", "USDT"), strategy_id: ID, by_pair: [] }),
      );
    }
    if (url.endsWith("/api/subscriptions/held")) return Promise.resolve(jsonResponse(held));
    if (url.includes("/api/subscriptions/") && init?.method === "PATCH") {
      return Promise.resolve(jsonResponse(heldSubscription({ strategy_id: ID, leverage: 4 })));
    }
    if (url.includes(`/strategies/${ID}/share-preview`)) return Promise.resolve(jsonResponse(unsyncedSharePreview(ID)));
    if (url.endsWith("/api/me")) {
      return Promise.resolve(
        jsonResponse({ email: "a@example.com", is_admin: true, mode: "LIVE", dry_run_brake: false, ...SIGNED_UP }),
      );
    }
    return undefined;
  });
}

const subscribeAside = () => screen.getByRole("complementary", { name: en.strategies.subscribe.title });

describe("the aside of another author's strategy (ex11)", () => {
  it("draws Subscribe's fields as the prototype does: the unit inside, no confirm button, each field a block of its own", async () => {
    serve();
    renderAt(<AppRoutes />, `/strategies/explore/${ID}`);
    const share = await screen.findByRole("textbox", { name: en.strategies.detail.share.label });
    const leverage = within(subscribeAside()).getByRole("textbox", { name: en.strategies.leverage.label });
    for (const [input, unit] of [
      [share, "%"],
      [leverage, "x"],
    ] as const) {
      const box = input.parentElement as HTMLElement;
      expect(box).toHaveClass("h-9.5", "rounded-lg", "bg-ground");
      expect(input).toHaveClass("flex-1");
      expect(box.lastElementChild).toBe(within(box).getByText(unit));
    }
    // Subscribing is the one button: nothing is saved field by field.
    expect(within(subscribeAside()).queryByRole("button", { name: en.strategies.detail.share.save })).toBeNull();
    const blocks = [share, leverage].map((input) => input.closest('[role="group"]'));
    expect(blocks[0]).not.toBeNull();
    expect(blocks[0]).not.toBe(blocks[1]);
    for (const block of blocks) expect(block).toHaveClass("flex", "flex-col");
    // A form of 16 px between its fields.
    expect(blocks[0]?.parentElement).toHaveClass("gap-4");
  });

  it("keeps the Subscribe button at the width of its text, 44 px high, in the green outline (L27)", async () => {
    serve();
    renderAt(<AppRoutes />, `/strategies/explore/${ID}`);
    const button = await screen.findByRole("button", { name: en.strategies.subscribe.submit });
    expect(button).toHaveClass("min-h-11", "rounded-lg", "border-gain/45", "text-gain-bright");
    expect(button).not.toHaveClass("bg-gain");
    expect(button.parentElement).not.toHaveClass("w-full");
  });

  it("draws the seat of a subscriber with the same fields and confirm buttons", async () => {
    serve([heldSubscription({ strategy_id: ID, leverage: 2 })]);
    renderAt(<AppRoutes />, `/strategies/explore/${ID}`);
    const aside = await screen.findByRole("complementary", { name: en.strategies.subscribe.seatTitle });
    const saves = within(aside).getAllByRole("button", { name: en.strategies.detail.share.save });
    expect(saves).toHaveLength(2);
    for (const save of saves) expect(save).toHaveClass("size-9", "bg-panel");
    expect(within(aside).getByRole("button", { name: en.strategies.subscriptions.leave })).toBeInTheDocument();
  });
});
