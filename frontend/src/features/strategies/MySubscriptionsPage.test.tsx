import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import i18n from "@/shared/i18n";
import { DANGER_CONTROL } from "@/shared/ui/danger-control";
import {
  heldSubscription,
  jsonResponse,
  renderAt,
  resetExchangeScope,
  setViewport,
  stubApi,
  unlock,
  unsyncedSharePreview,
} from "@/test/harness";

const STRATEGY_ID = "11111111-1111-4111-8111-111111111111";

interface Serve {
  held: () => Promise<Response>;
  leave?: () => Promise<Response>;
  patch?: () => Promise<Response>;
}

function serve({ held, leave, patch }: Serve) {
  return stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url, init) => {
    if (url.endsWith("/api/subscriptions/held")) return held();
    if (url.endsWith("/leave") && init?.method === "POST") return leave?.();
    if (url.includes("/api/subscriptions/") && init?.method === "PATCH") return patch?.();
    if (url.includes(`/strategies/${STRATEGY_ID}/share-preview`)) {
      return Promise.resolve(jsonResponse(unsyncedSharePreview(STRATEGY_ID)));
    }
    return undefined;
  });
}

function open() {
  renderAt(<AppRoutes />, "/strategies");
}

function requestsTo(fetchMock: ReturnType<typeof stubApi>, ending: string) {
  return fetchMock.mock.calls.filter(([url]) => String(url).endsWith(ending));
}

beforeEach(() => {
  unlock();
  resetExchangeScope();
  setViewport("wide");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the tabs of Strategies", () => {
  it("offers the three lists and marks the one on screen", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([])) });
    open();

    expect(await screen.findByRole("heading", { level: 1, name: i18n.t("strategies.title") })).toBeInTheDocument();
    const tabs = screen.getByRole("navigation", { name: i18n.t("strategies.tabs.label") });
    const links = within(tabs).getAllByRole("link");
    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      [i18n.t("strategies.tabs.subscriptions"), "/strategies"],
      [i18n.t("strategies.tabs.explore"), "/strategies/explore"],
      [i18n.t("strategies.tabs.authored"), "/strategies/authored"],
    ]);
    expect(links[0]).toHaveAttribute("aria-current", "page");
    expect(links[1]).not.toHaveAttribute("aria-current");
  });

  it("names the third list My strategies", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([])) });
    open();

    const tabs = await screen.findByRole("navigation", { name: i18n.t("strategies.tabs.label") });
    expect(within(tabs).getByRole("link", { name: "My strategies" })).toHaveAttribute("href", "/strategies/authored");
  });

  it("puts a decorative icon before the label of each list", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([])) });
    open();

    const tabs = await screen.findByRole("navigation", { name: i18n.t("strategies.tabs.label") });
    const links = within(tabs).getAllByRole("link");
    expect(links).toHaveLength(3);
    for (const link of links) {
      const icon = link.querySelector("svg");
      expect(icon).not.toBeNull();
      expect(icon).toHaveAttribute("aria-hidden", "true");
      expect(link.firstElementChild).toBe(icon);
    }
  });

  it("keeps My subscriptions unmarked on another list", async () => {
    stubApi({ kind: "ok", body: {} }, [], { kind: "ok", body: [] }, {}, (url) =>
      url.endsWith("/api/public/strategies") ? Promise.resolve(jsonResponse([])) : undefined,
    );
    renderAt(<AppRoutes />, "/strategies/explore");

    const tabs = await screen.findByRole("navigation", { name: i18n.t("strategies.tabs.label") });
    expect(within(tabs).getByRole("link", { name: i18n.t("strategies.tabs.subscriptions") })).not.toHaveAttribute(
      "aria-current",
    );
    expect(within(tabs).getByRole("link", { name: i18n.t("strategies.tabs.explore") })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});

describe("My subscriptions", () => {
  it("shows what is held: the strategy, its author, its market and the share", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription()])) });
    open();

    const row = await screen.findByTestId("subscription-row");
    expect(within(row).getByRole("link", { name: "Alpha" })).toHaveAttribute("href", `/strategies/explore/${STRATEGY_ID}`);
    expect(within(row).getByTestId("subscription-origin")).toHaveTextContent(
      `${i18n.t("strategies.subscriptions.by", { name: "Ana" })} · bybit · usdt-m · USDT`,
    );
    expect(within(row).getByTestId("subscription-share")).toHaveTextContent(
      i18n.t("strategies.subscriptions.share", { share: "30" }),
    );
  });

  it("draws Leave in red with an icon", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription()])) });
    open();

    const leave = await screen.findByRole("button", { name: i18n.t("strategies.subscriptions.leave") });
    expect(leave).toHaveClass("border-loss", "text-loss");
    expect(leave.className).toBe(DANGER_CONTROL);
    expect(leave.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("writes the share in plain form, however the server wrote it", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription({ allocation_percent: "30.000000" })])) });
    open();

    expect(await screen.findByTestId("subscription-share")).toHaveTextContent(
      i18n.t("strategies.subscriptions.share", { share: "30" }),
    );
  });

  it("says an author has no name yet, instead of a blank", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription({ author_name: null })])) });
    open();

    expect(await screen.findByTestId("subscription-origin")).toHaveTextContent(
      i18n.t("strategies.subscriptions.noAuthorName"),
    );
  });

  it("sends an author to their own page and offers no way out", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription({ authored: true })])) });
    open();

    const row = await screen.findByTestId("subscription-row");
    expect(within(row).getByRole("link", { name: "Alpha" })).toHaveAttribute("href", `/strategies/${STRATEGY_ID}`);
    expect(within(row).getByTestId("subscription-origin")).toHaveTextContent(i18n.t("strategies.subscriptions.yours"));
    expect(within(row).queryByRole("button")).not.toBeInTheDocument();
  });

  it("tells a leaving subscription apart and offers nothing on it", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription({ status: "LEAVING" })])) });
    open();

    const row = await screen.findByTestId("subscription-row");
    expect(within(row).getByText(i18n.t("strategies.subscriptions.leaving"))).toBeInTheDocument();
    expect(within(row).queryByRole("button")).not.toBeInTheDocument();
  });

  it("says nothing of leaving on a subscription that is not leaving", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription()])) });
    open();

    await screen.findByTestId("subscription-row");
    expect(screen.queryByText(i18n.t("strategies.subscriptions.leaving"))).not.toBeInTheDocument();
  });

  it("points an empty list at Explore", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([])) });
    open();

    expect(await screen.findByText(i18n.t("strategies.subscriptions.empty"))).toBeInTheDocument();
    expect(screen.getByRole("link", { name: i18n.t("strategies.subscriptions.explore") })).toHaveAttribute(
      "href",
      "/strategies/explore",
    );
  });

  it("reads a failed list as an error, never as an empty one", async () => {
    serve({ held: () => Promise.resolve(jsonResponse({ detail: "down" }, 500)) });
    open();

    expect(await screen.findByRole("alert")).toHaveTextContent(i18n.t("strategies.subscriptions.error"));
    expect(screen.queryByText(i18n.t("strategies.subscriptions.empty"))).not.toBeInTheDocument();
  });

  it("says it is loading while the list is on its way", async () => {
    serve({ held: () => new Promise<Response>(() => undefined) });
    open();

    expect(await screen.findByText(i18n.t("strategies.subscriptions.loading"))).toBeInTheDocument();
  });
});

describe("a seat in the list is a summary", () => {
  it("shows its share and leverage as text, links to the strategy and holds no editor and no Save", async () => {
    const fetchMock = serve({ held: () => Promise.resolve(jsonResponse([heldSubscription({ leverage: 4 })])) });
    open();

    const row = await screen.findByTestId("subscription-row");
    expect(within(row).getByTestId("subscription-share")).toHaveTextContent(
      i18n.t("strategies.subscriptions.share", { share: "30" }),
    );
    expect(within(row).getByTestId("subscription-leverage")).toHaveTextContent(
      i18n.t("strategies.subscriptions.leverage", { leverage: 4 }),
    );
    expect(within(row).getByRole("link", { name: "Alpha" })).toHaveAttribute("href", `/strategies/explore/${STRATEGY_ID}`);
    expect(within(row).queryByRole("textbox")).not.toBeInTheDocument();
    expect(within(row).queryByRole("slider")).not.toBeInTheDocument();
    expect(within(row).getAllByRole("button").map((button) => button.textContent)).toEqual([
      i18n.t("strategies.subscriptions.leave"),
    ]);
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/share-preview"))).toBe(false);
  });

  it("links an authored seat to the author's own page", async () => {
    serve({ held: () => Promise.resolve(jsonResponse([heldSubscription({ authored: true, leverage: 2 })])) });
    open();

    const row = await screen.findByTestId("subscription-row");
    expect(within(row).getByRole("link", { name: "Alpha" })).toHaveAttribute("href", `/strategies/${STRATEGY_ID}`);
    expect(within(row).getByTestId("subscription-leverage")).toHaveTextContent(
      i18n.t("strategies.subscriptions.leverage", { leverage: 2 }),
    );
  });
});

describe("leaving", () => {
  const leaveName = () => i18n.t("strategies.subscriptions.leave");
  /** Inside the dialog: the row behind it holds a button of the same name, which a real modal makes inert. */
  const confirmButton = () =>
    within(screen.getByRole("dialog")).getByRole("button", { name: i18n.t("strategies.leave.confirm") });

  it("asks first: opening the dialog sends nothing, and says what happens to a position", async () => {
    const fetchMock = serve({ held: () => Promise.resolve(jsonResponse([heldSubscription()])) });
    open();

    fireEvent.click(await screen.findByRole("button", { name: leaveName() }));

    const dialog = await screen.findByRole("dialog", { name: i18n.t("strategies.leave.confirmTitle", { name: "Alpha" }) });
    expect(within(dialog).getByText(i18n.t("strategies.leave.confirmBody", { name: "Alpha" }))).toBeInTheDocument();
    expect(within(dialog).getByText(i18n.t("strategies.leave.privateNote"))).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/leave"))).toHaveLength(0);
  });

  it.each([
    ["the cancel button", () => fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.leave.cancel") }))],
    ["Escape", () => fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" })],
    ["the browser's cancel", () => fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true }))],
  ])("%s sends nothing and closes", async (_name, dismiss) => {
    const fetchMock = serve({ held: () => Promise.resolve(jsonResponse([heldSubscription()])) });
    open();

    fireEvent.click(await screen.findByRole("button", { name: leaveName() }));
    dismiss();

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/leave"))).toHaveLength(0);
  });

  it("confirming posts the leave of that subscription, closes and reads the list again", async () => {
    const row = heldSubscription();
    let leaveCalled = false;
    const fetchMock = serve({
      held: () => Promise.resolve(jsonResponse(leaveCalled ? [] : [row])),
      leave: () => {
        leaveCalled = true;
        return Promise.resolve(jsonResponse({ ...row, status: "ENDED" }));
      },
    });
    open();

    fireEvent.click(await screen.findByRole("button", { name: leaveName() }));
    fireEvent.click(confirmButton());

    await waitFor(() => expect(requestsTo(fetchMock, `/api/subscriptions/${row.id}/leave`)).toHaveLength(1));
    expect(await screen.findByText(i18n.t("strategies.subscriptions.empty"))).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("a position still open leaves the row in place, marked as leaving, with the dialog closed", async () => {
    const row = heldSubscription();
    let leaveCalled = false;
    serve({
      held: () => Promise.resolve(jsonResponse([leaveCalled ? { ...row, status: "LEAVING" } : row])),
      leave: () => {
        leaveCalled = true;
        return Promise.resolve(jsonResponse({ ...row, status: "LEAVING" }));
      },
    });
    open();

    fireEvent.click(await screen.findByRole("button", { name: leaveName() }));
    fireEvent.click(confirmButton());

    expect(await screen.findByText(i18n.t("strategies.subscriptions.leaving"))).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("holds while the leave is on its way: nothing presses it twice and Escape does not close it", async () => {
    serve({
      held: () => Promise.resolve(jsonResponse([heldSubscription()])),
      leave: () => new Promise<Response>(() => undefined),
    });
    open();

    fireEvent.click(await screen.findByRole("button", { name: leaveName() }));
    fireEvent.click(confirmButton());

    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByRole("button", { name: i18n.t("strategies.leave.pending") })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: i18n.t("strategies.leave.cancel") })).toBeDisabled();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("opening the dialog again forgets the last refusal", async () => {
    serve({
      held: () => Promise.resolve(jsonResponse([heldSubscription()])),
      leave: () => Promise.resolve(jsonResponse({ detail: "boom" }, 500)),
    });
    open();

    fireEvent.click(await screen.findByRole("button", { name: leaveName() }));
    fireEvent.click(confirmButton());
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: i18n.t("strategies.leave.cancel") }));
    fireEvent.click(screen.getByRole("button", { name: leaveName() }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    [409, { error: "AUTHOR_CANNOT_LEAVE", message: "no" }, "strategies.leave.errors.author"],
    [409, { error: "SUBSCRIPTION_NOT_ACTIVE", message: "no" }, "strategies.leave.errors.notActive"],
    [404, "no subscription", "strategies.leave.errors.gone"],
    [500, "boom", "strategies.leave.errors.generic"],
  ])("a %i refusal is in words, inside the dialog", async (status, detail, key) => {
    serve({
      held: () => Promise.resolve(jsonResponse([heldSubscription()])),
      leave: () => Promise.resolve(jsonResponse({ detail }, status)),
    });
    open();

    fireEvent.click(await screen.findByRole("button", { name: leaveName() }));
    fireEvent.click(confirmButton());

    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(i18n.t(key));
  });
});
