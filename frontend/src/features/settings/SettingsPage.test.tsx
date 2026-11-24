import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import { lock, pool, renderAt, resetExchangeScope, storedKey, stubApi, unlock } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await i18n.changeLanguage("en");
});

/** Mi cuenta (S4, ex7): the person's data, the legal acceptance and the account's deletion. The keys moved. */
describe("My account", () => {
  function mount() {
    const fetchMock = stubApi(HEALTH, [], { kind: "ok", body: [pool("bybit")] }, {}, undefined, {}, {
      kind: "ok",
      body: [storedKey("bybit")],
    });
    renderAt(<AppRoutes />, "/settings");
    return fetchMock;
  }

  it("keeps the person's data and the deletion of the account, under its own title and subtitle", async () => {
    mount();

    expect(await screen.findByRole("heading", { level: 1, name: "My account" })).toBeInTheDocument();
    expect(screen.getByText(en.pageHeader.account)).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: "Profile" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Delete account" })).toBeInTheDocument();
  });

  it("draws no key card, no key section and no `Link exchange` action: the keys live in Link exchange", async () => {
    mount();
    await screen.findByRole("heading", { level: 2, name: "Delete account" });

    expect(screen.queryByRole("heading", { level: 2, name: "Exchange keys" })).not.toBeInTheDocument();
    expect(screen.queryAllByRole("article")).toEqual([]);
    expect(screen.queryByRole("button", { name: "Link exchange" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^(Add|Replace|Delete) key/ })).not.toBeInTheDocument();
  });

  it("never reads the keys or the pools", async () => {
    const fetchMock = mount();
    await screen.findByRole("heading", { level: 2, name: "Delete account" });
    // The shell reads what it needs; the page itself asks for no key.
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(0));

    const settingsReads = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/credentials"));
    expect(settingsReads).toEqual([]);
  });
});
