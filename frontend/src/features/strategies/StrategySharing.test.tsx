import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StrategyDetailPage } from "@/features/strategies/StrategyDetailPage";
import i18n from "@/shared/i18n";
import { jsonResponse, lock, renderAt, resetExchangeScope, stubApi, strategyRoute, unlock } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const CODE_A = "22222222-2222-4222-8222-222222222222";
const CODE_B = "33333333-3333-4333-8333-333333333333";
const TOKEN = "Zr8kQ2vN_x1yPq3sLm4tB5wC6dE7fG8hJ9kL0mN1oP2";
const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const LIVE_A = { id: CODE_A, hint: "VRXT", expires_at: "2026-11-14T10:00:00+00:00" };
const LIVE_B = { id: CODE_B, hint: "Q9WD", expires_at: "2026-11-15T08:30:00+00:00" };
const ISSUED = { id: CODE_B, hint: "Q9WD", expires_at: LIVE_B.expires_at, code: "K7MP-Q9WD" };

interface Call {
  method: string;
  url: string;
  body?: unknown;
}

interface Answers {
  /** The live codes, answered by every GET of the list. Changed by the test between reads. */
  codes: unknown[] | Response;
  issue?: Response;
  revoke?: Response;
  /** The PATCH answer: "saved" stores the visibility asked for, with `share_token` when it is LINK. */
  patch?: "saved";
}

/** The strategy's page with a stored state, recording every request to the codes and every PATCH. */
function setup(stored: Record<string, unknown>, answers: Answers = { codes: [] }) {
  const calls: Call[] = [];
  let current = { ...stored };
  stubApi(HEALTH, [], undefined, {}, (url, init) => {
    const method = init?.method ?? "GET";
    if (url.includes(`/strategies/${ID}/invite-codes`)) {
      calls.push({ method, url });
      if (method === "POST") return Promise.resolve(answers.issue ?? jsonResponse(ISSUED, 201));
      if (method === "DELETE") return Promise.resolve(answers.revoke ?? new Response(null, { status: 204 }));
      const listed = answers.codes;
      return Promise.resolve(listed instanceof Response ? listed.clone() : jsonResponse(listed));
    }
    if (method === "PATCH" && url.endsWith(`/strategies/${ID}`)) {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      calls.push({ method, url, body });
      if (answers.patch !== "saved") return Promise.resolve(jsonResponse({}, 500));
      current = { ...current, ...body, share_token: body.visibility === "LINK" ? TOKEN : null };
    }
    return strategyRoute(ID, "ETH Breakout", current)(url, init);
  });
  renderAt(
    <Routes>
      <Route path="strategies/:strategyId" element={<StrategyDetailPage />} />
    </Routes>,
    `/strategies/${ID}`,
  );
  return { calls, answers };
}

function stubClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  return writeText;
}

const field = () => screen.findByLabelText("Visibility") as Promise<HTMLSelectElement>;
const codeRequests = (calls: Call[], method: string) => calls.filter((call) => call.method === method && call.url.includes("invite-codes"));
const linkOf = (token: string) => `${window.location.origin}/strategies/explore/${ID}?link=${token}`;
const LINK_HINT =
  "Whoever opens this link sees the strategy and may subscribe. Changing the visibility stops this link; choosing With link again makes a new one.";
const CODES_HINT = "Each code lets one person subscribe, once, within 7 days of its creation.";
/** Whether `before` comes before `after` in the document, which is the order on screen. */
const precedes = (before: Element, after: Element) =>
  (before.compareDocumentPosition(after) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "clipboard");
  lock();
  await act(() => i18n.changeLanguage("en"));
});

describe("the visibility selector, with a link", () => {
  it("offers Private, With link and Public, in that order", async () => {
    setup({ visibility: "LINK", share_token: TOKEN });

    const select = await field();

    expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual(["Private", "With link", "Public"]);
    expect(select.value).toBe("LINK");
  });

  it("sends LINK when With link is chosen, and shows the link the answer carries", async () => {
    const { calls } = setup({ visibility: "PRIVATE" }, { codes: [], patch: "saved" });

    fireEvent.change(await field(), { target: { value: "LINK" } });

    expect(await screen.findByDisplayValue(linkOf(TOKEN))).toBeInTheDocument();
    expect(calls.filter((call) => call.method === "PATCH").map((call) => call.body)).toEqual([{ visibility: "LINK" }]);
  });

  it("says what each visibility means", async () => {
    setup({ visibility: "PUBLIC" });

    await field();

    expect(
      screen.getByText(
        "Public: listed on Explore. With link: only who has the link sees it and may subscribe. Private: only who holds an invitation code. Subscribers it already has keep it.",
      ),
    ).toBeInTheDocument();
  });
});

describe("a strategy shared by its link", () => {
  it("shows the link to its public page on one line that scrolls, read-only, in the strategy's settings", async () => {
    setup({ visibility: "LINK", share_token: TOKEN });

    const link = await screen.findByRole("textbox", { name: "Link to this strategy" });

    expect(link).toBeInstanceOf(HTMLInputElement);
    expect(link).toHaveValue(linkOf(TOKEN));
    expect(link).toHaveAttribute("readonly");
    expect(link.closest("aside")).not.toBeNull();
  });

  it("explains the link behind its information button, beside the title", async () => {
    setup({ visibility: "LINK", share_token: TOKEN });
    const info = await screen.findByRole("button", { name: "About the link" });

    expect(screen.queryByText(LINK_HINT)).toBeNull();
    fireEvent.click(info);

    expect(screen.getByText(LINK_HINT)).toBeInTheDocument();
  });

  it("sits right under the settings' title and visibility, above the share of the pool", async () => {
    setup({ visibility: "LINK", share_token: TOKEN });

    const title = await screen.findByRole("heading", { name: "Link to this strategy" });
    const share = await screen.findByRole("textbox", { name: i18n.t("strategies.detail.share.label") });

    expect(precedes(screen.getByLabelText("Visibility"), title)).toBe(true);
    expect(precedes(title, share)).toBe(true);
  });

  it("copies the link with an icon button whose tip says Copy link, and the button says it did", async () => {
    const writeText = stubClipboard();
    setup({ visibility: "LINK", share_token: TOKEN });
    const button = await screen.findByRole("button", { name: "Copy link" });

    expect(button).toHaveTextContent("");
    // One keyboard stop: the tip's wrapper does not take focus beside the button.
    expect(button.parentElement).not.toHaveAttribute("tabindex");
    fireEvent.mouseEnter(button.parentElement as HTMLElement);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Copy link");
    fireEvent.click(button);

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(linkOf(TOKEN)));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("says in words when the link could not be copied", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
      configurable: true,
    });
    setup({ visibility: "LINK", share_token: TOKEN });

    fireEvent.click(await screen.findByRole("button", { name: "Copy link" }));

    expect(await screen.findByText(i18n.t("strategies.webhook.copyFailed"))).toBeInTheDocument();
  });

  it("reads no invitation codes", async () => {
    const { calls } = setup({ visibility: "LINK", share_token: TOKEN });

    await screen.findByDisplayValue(linkOf(TOKEN));

    expect(screen.queryByRole("button", { name: "Create code" })).toBeNull();
    expect(codeRequests(calls, "GET")).toEqual([]);
  });
});

describe("a public strategy", () => {
  it("shows no link and no codes, and reads none", async () => {
    const { calls } = setup({ visibility: "PUBLIC" });

    await field();

    expect(screen.queryByRole("button", { name: "Copy link" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Create code" })).toBeNull();
    expect(codeRequests(calls, "GET")).toEqual([]);
  });
});

describe("a private strategy's invitation codes", () => {
  it("lists the unused codes by their last four characters and their expiry, in UTC", async () => {
    setup({ visibility: "PRIVATE" }, { codes: [LIVE_A, LIVE_B] });

    const list = await screen.findByRole("list", { name: "Unused codes" });
    const rows = within(list).getAllByRole("listitem");

    expect(rows.map((row) => row.textContent)).toEqual([
      "····-VRXTExpires Nov 14, 2026, 10:00 UTC",
      "····-Q9WDExpires Nov 15, 2026, 08:30 UTC",
    ]);
    expect(list.closest("aside")).not.toBeNull();
  });

  it("explains the codes behind their information button, beside the title", async () => {
    setup({ visibility: "PRIVATE" }, { codes: [] });
    const info = await screen.findByRole("button", { name: "About invitation codes" });

    expect(screen.queryByText(CODES_HINT)).toBeNull();
    fireEvent.click(info);

    expect(screen.getByText(CODES_HINT)).toBeInTheDocument();
  });

  it("sit right under the settings' title and visibility, above the share of the pool", async () => {
    setup({ visibility: "PRIVATE" }, { codes: [] });

    const title = await screen.findByRole("heading", { name: "Invitation codes" });
    const share = await screen.findByRole("textbox", { name: i18n.t("strategies.detail.share.label") });

    expect(precedes(screen.getByLabelText("Visibility"), title)).toBe(true);
    expect(precedes(title, share)).toBe(true);
  });

  it("says when there is no unused code", async () => {
    setup({ visibility: "PRIVATE" }, { codes: [] });

    expect(await screen.findByText("No unused codes.")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Unused codes" })).toBeNull();
  });

  it("says when the codes could not be loaded, and never shows an empty list", async () => {
    setup({ visibility: "PRIVATE" }, { codes: jsonResponse({ detail: "boom" }, 500) });

    expect(await screen.findByText("The codes could not be loaded.")).toBeInTheDocument();
    expect(screen.queryByText("No unused codes.")).toBeNull();
  });

  it("creates a code and shows it once, with its expiry, then reads the list again", async () => {
    const { calls, answers } = setup({ visibility: "PRIVATE" }, { codes: [LIVE_A] });
    await screen.findByRole("list", { name: "Unused codes" });
    answers.codes = [LIVE_A, LIVE_B];

    fireEvent.click(screen.getByRole("button", { name: "Create code" }));

    const issued = await screen.findByRole("region", { name: "New code" });
    expect(within(issued).getByText("K7MP-Q9WD")).toBeInTheDocument();
    expect(within(issued).getByText("Expires Nov 15, 2026, 08:30 UTC")).toBeInTheDocument();
    expect(within(issued).getByText("It is shown only once: copy it now and send it to the person you invite.")).toBeInTheDocument();
    expect(codeRequests(calls, "POST")).toHaveLength(1);
    await waitFor(() => expect(codeRequests(calls, "GET")).toHaveLength(2));
    expect(await screen.findByText("····-Q9WD")).toBeInTheDocument();
  });

  it("copies the new code", async () => {
    const writeText = stubClipboard();
    setup({ visibility: "PRIVATE" }, { codes: [] });

    fireEvent.click(await screen.findByRole("button", { name: "Create code" }));
    fireEvent.click(await screen.findByRole("button", { name: "Copy code" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("K7MP-Q9WD"));
  });

  it("puts the new code away with Done, and it is not shown again", async () => {
    setup({ visibility: "PRIVATE" }, { codes: [] });

    fireEvent.click(await screen.findByRole("button", { name: "Create code" }));
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));

    await waitFor(() => expect(screen.queryByText("K7MP-Q9WD")).toBeNull());
    expect(screen.queryByRole("region", { name: "New code" })).toBeNull();
  });

  it.each([
    [jsonResponse({ detail: { error: "STRATEGY_NOT_PRIVATE", message: "x" } }, 409), "The strategy is no longer private, so no code was created."],
    [jsonResponse({ detail: { error: "AUTHOR_HAS_NO_DISPLAY_NAME", message: "x" } }, 409), "Choose your name in Settings first: a strategy offered to others shows its author."],
    [jsonResponse({ detail: { error: "STRATEGY_ARCHIVED", message: "x" } }, 409), "This strategy is archived and can no longer change."],
    [jsonResponse({ detail: "no such strategy" }, 404), "This strategy no longer exists."],
    [jsonResponse({ detail: "boom" }, 500), "The code was not created. Try again."],
  ])("says why a code was not created (%#), and shows none", async (answer, text) => {
    setup({ visibility: "PRIVATE" }, { codes: [], issue: answer });

    fireEvent.click(await screen.findByRole("button", { name: "Create code" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(screen.queryByRole("region", { name: "New code" })).toBeNull();
  });

  it("revokes a code with its ✕, then reads the list again", async () => {
    const { calls, answers } = setup({ visibility: "PRIVATE" }, { codes: [LIVE_A, LIVE_B] });
    await screen.findByRole("list", { name: "Unused codes" });
    answers.codes = [LIVE_B];

    fireEvent.click(screen.getByRole("button", { name: "Revoke the code ending in VRXT" }));

    await waitFor(() => expect(screen.queryByText("····-VRXT")).toBeNull());
    expect(codeRequests(calls, "DELETE").map((call) => call.url)).toEqual([expect.stringMatching(new RegExp(`/strategies/${ID}/invite-codes/${CODE_A}$`))]);
    expect(screen.getByText("····-Q9WD")).toBeInTheDocument();
  });

  it.each([
    [jsonResponse({ detail: "no such code" }, 404), "That code was already used, expired or revoked."],
    [jsonResponse({ detail: "boom" }, 500), "The code was not revoked. Try again."],
  ])("says why a code was not revoked (%#)", async (answer, text) => {
    setup({ visibility: "PRIVATE" }, { codes: [LIVE_A], revoke: answer });

    fireEvent.click(await screen.findByRole("button", { name: "Revoke the code ending in VRXT" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(text);
  });

  it("creates no code for an archived strategy, and still lists and revokes", async () => {
    setup({ visibility: "PRIVATE", archived_at: "2026-10-01T00:00:00Z" }, { codes: [LIVE_A] });

    await screen.findByRole("list", { name: "Unused codes" });

    expect(screen.getByRole("button", { name: "Create code" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Revoke the code ending in VRXT" })).toBeEnabled();
  });
});

describe("sharing, in Spanish", () => {
  it("says the link and the codes with usted", async () => {
    await act(() => i18n.changeLanguage("es"));
    setup({ visibility: "PRIVATE" }, { codes: [LIVE_A] });

    expect(await screen.findByRole("button", { name: "Crear código" })).toBeInTheDocument();
    expect(await screen.findByRole("list", { name: "Códigos sin usar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revocar el código que termina en VRXT" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Acerca de los códigos de invitación" }));
    expect(screen.getByText("Cada código permite que una persona se suscriba, una sola vez, dentro de los 7 días de su creación.")).toBeInTheDocument();
    const select = screen.getByLabelText("Visibilidad") as HTMLSelectElement;
    expect(within(select).getAllByRole("option").map((option) => option.textContent)).toEqual(["Privada", "Con enlace", "Pública"]);
  });
});
