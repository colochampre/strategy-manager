import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CONFIRMED_KEY, useConfirmedDiscrepancies } from "@/shared/api/discrepancies";
import { ModeBadge } from "@/shared/layout/ModeBadge";
import { jsonResponse, renderAt, stubApi, unlock } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: false } } as const;

const REAL_ORDERS = "Real orders will be placed on your exchanges with your capital, from the next opening signal on.";

interface Server {
  mode: "LIVE" | "SIMULATION";
  brake: boolean;
  /** Answers the POST instead of accepting it. */
  refuse?: () => Response;
  /** Holds the POST until the test resolves it. */
  hold?: Promise<Response>;
}

function serve(server: Server) {
  return stubApi(HEALTH, [], undefined, {}, (url, init) => {
    if (url.endsWith("/api/me")) {
      return Promise.resolve(
        jsonResponse({ email: "owner@example.com", is_admin: true, mode: server.mode, dry_run_brake: server.brake }),
      );
    }
    if (!url.endsWith("/api/me/mode")) return undefined;
    if (server.hold !== undefined) return server.hold;
    if (server.refuse !== undefined) return Promise.resolve(server.refuse());
    server.mode = (JSON.parse(String(init?.body)) as { mode: Server["mode"] }).mode;
    return Promise.resolve(
      jsonResponse({ email: "owner@example.com", is_admin: true, mode: server.mode, dry_run_brake: server.brake }),
    );
  });
}

function posts(fetchMock: ReturnType<typeof stubApi>) {
  return fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/me/mode"));
}

function refusal(error: string, symbols: string[] = []) {
  return () => jsonResponse({ detail: { error, message: "server wording", symbols } }, 409);
}

async function openDialog(name: RegExp) {
  fireEvent.click(await screen.findByRole("button", { name }));
  return screen.findByRole("dialog");
}

beforeEach(() => {
  unlock();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("what the badge says", () => {
  it("says Simulation in amber, as a button", async () => {
    serve({ mode: "SIMULATION", brake: false });
    renderAt(<ModeBadge />);

    const badge = await screen.findByText("Simulation");
    expect(badge).toHaveClass("text-decision", "border-decision");
    expect(screen.getByRole("button", { name: /Mode: Simulation/ })).toContainElement(badge);
  });

  it("says Live in the gain colour, as a button", async () => {
    serve({ mode: "LIVE", brake: false });
    renderAt(<ModeBadge />);

    const badge = await screen.findByText("Live");
    expect(badge).toHaveClass("text-gain", "border-gain");
    expect(badge).not.toHaveClass("text-loss");
    expect(screen.getByRole("button", { name: /Mode: Live/ })).toContainElement(badge);
  });

  it.each(["SIMULATION", "LIVE"] as const)(
    "says simulation is forced for everyone when the brake is on, and cannot be clicked (user in %s)",
    async (mode) => {
      serve({ mode, brake: true });
      renderAt(<ModeBadge />);

      const badge = await screen.findByText("Simulation forced");
      expect(badge).toHaveClass("text-decision");
      expect(badge).toHaveAttribute("title", "The brake is on: everyone is in simulation until it is released.");
      expect(screen.queryByRole("button")).not.toBeInTheDocument();
      expect(screen.queryByText("Live")).not.toBeInTheDocument();
    },
  );

  it("stays neutral while it is asked, never Live", () => {
    stubApi(HEALTH, [], undefined, {}, (url) =>
      url.endsWith("/api/me") ? new Promise<Response>(() => undefined) : undefined,
    );
    renderAt(<ModeBadge />);

    expect(screen.getByText("Checking mode")).toHaveClass("text-ink-3");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it.each([
    ["the network fails", () => Promise.reject(new TypeError("offline"))],
    ["a 500", () => Promise.resolve(jsonResponse({}, 500))],
    ["a body with no mode", () => Promise.resolve(jsonResponse({ email: "a@b.c", is_admin: true, dry_run_brake: false }))],
  ])("says Mode unknown, never Live, on %s", async (_name, answer) => {
    stubApi(HEALTH, [], undefined, {}, (url) => (url.endsWith("/api/me") ? answer() : undefined));
    renderAt(<ModeBadge />);

    expect(await screen.findByText("Mode unknown")).toHaveClass("text-ink-3");
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("changing the mode", () => {
  it("asks first: the click sends nothing, and Cancel has the focus", async () => {
    const fetchMock = serve({ mode: "SIMULATION", brake: false });
    renderAt(<ModeBadge />);

    const dialog = await openDialog(/Mode: Simulation/);

    expect(within(dialog).getByRole("heading", { name: "Go live?" })).toBeInTheDocument();
    expect(within(dialog).getByText(REAL_ORDERS)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(posts(fetchMock)).toHaveLength(0);
  });

  it("sends nothing on Cancel", async () => {
    const fetchMock = serve({ mode: "SIMULATION", brake: false });
    renderAt(<ModeBadge />);
    const dialog = await openDialog(/Mode: Simulation/);

    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posts(fetchMock)).toHaveLength(0);
    expect(screen.getByText("Simulation")).toBeInTheDocument();
  });

  it("goes live on the dialog's own button, and the badge follows", async () => {
    const fetchMock = serve({ mode: "SIMULATION", brake: false });
    renderAt(<ModeBadge />);
    const dialog = await openDialog(/Mode: Simulation/);

    fireEvent.click(within(dialog).getByRole("button", { name: "Go live" }));

    expect(await screen.findByText("Live")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posts(fetchMock)).toHaveLength(1);
    expect(JSON.parse(String(posts(fetchMock)[0]?.[1]?.body))).toEqual({ mode: "LIVE" });
  });

  it("goes back to simulation, saying no real order is placed", async () => {
    const fetchMock = serve({ mode: "LIVE", brake: false });
    renderAt(<ModeBadge />);
    const dialog = await openDialog(/Mode: Live/);

    expect(
      within(dialog).getByText("Openings will be simulated against your real balance. No real order is placed for them."),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Move to simulation" }));

    expect(await screen.findByText("Simulation")).toBeInTheDocument();
    expect(JSON.parse(String(posts(fetchMock)[0]?.[1]?.body))).toEqual({ mode: "SIMULATION" });
  });

  it("reads the discrepancies again, because whether they are compared follows the mode", async () => {
    const fetchMock = serve({ mode: "SIMULATION", brake: false });
    function Reader() {
      useConfirmedDiscrepancies();
      return <ModeBadge />;
    }
    renderAt(<Reader />);
    const confirmedReads = () =>
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith(CONFIRMED_KEY.join("/"))).length;
    const dialog = await openDialog(/Mode: Simulation/);
    await waitFor(() => expect(confirmedReads()).toBe(1));

    fireEvent.click(within(dialog).getByRole("button", { name: "Go live" }));

    await waitFor(() => expect(confirmedReads()).toBe(2));
  });

  it("holds the dialog while the change is in flight", async () => {
    let release: (response: Response) => void = () => undefined;
    const hold = new Promise<Response>((resolve) => {
      release = resolve;
    });
    serve({ mode: "SIMULATION", brake: false, hold });
    renderAt(<ModeBadge />);
    const dialog = await openDialog(/Mode: Simulation/);

    fireEvent.click(within(dialog).getByRole("button", { name: "Go live" }));

    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    await waitFor(() => expect(cancel).toBeDisabled());
    expect(within(dialog).getByRole("button", { name: "Changing…" })).toBeDisabled();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    release(jsonResponse({ email: "owner@example.com", is_admin: true, mode: "LIVE", dry_run_brake: false }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("closes on Escape when nothing is in flight", async () => {
    serve({ mode: "SIMULATION", brake: false });
    renderAt(<ModeBadge />);
    const dialog = await openDialog(/Mode: Simulation/);

    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("each refusal in words", () => {
  it("says a key that can trade is missing, and the mode stays", async () => {
    serve({ mode: "SIMULATION", brake: false, refuse: refusal("MODE_LIVE_NEEDS_TRADE_KEY") });
    renderAt(<ModeBadge />);
    const dialog = await openDialog(/Mode: Simulation/);

    fireEvent.click(within(dialog).getByRole("button", { name: "Go live" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Going live needs an active key that can trade. Add one in Settings.",
    );
    expect(screen.getByText("Simulation")).toBeInTheDocument();
  });

  it("lists the symbols of a flat refusal", async () => {
    serve({ mode: "LIVE", brake: false, refuse: refusal("MODE_SIMULATION_NEEDS_FLAT", ["SFPUSDT", "STXUSDT"]) });
    renderAt(<ModeBadge />);
    const dialog = await openDialog(/Mode: Live/);

    fireEvent.click(within(dialog).getByRole("button", { name: "Move to simulation" }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("Going to simulation needs nothing real held.");
    expect(within(alert).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["SFPUSDT", "STXUSDT"]);
  });

  it("says the brake is on, and keeps saying it after the badge has followed", async () => {
    const server: Server = { mode: "SIMULATION", brake: false };
    server.refuse = () => {
      server.brake = true;
      return refusal("MODE_BRAKE_ON")();
    };
    serve(server);
    renderAt(<ModeBadge />);
    const dialog = await openDialog(/Mode: Simulation/);

    fireEvent.click(within(dialog).getByRole("button", { name: "Go live" }));

    expect(await screen.findByText("Simulation forced")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The brake is on: everyone is in simulation until it is released, so the mode cannot change.",
    );
  });

  it("says the change failed on anything else, never with the server's words", async () => {
    serve({ mode: "SIMULATION", brake: false, refuse: () => jsonResponse({ detail: "server wording" }, 500) });
    renderAt(<ModeBadge />);
    const dialog = await openDialog(/Mode: Simulation/);

    fireEvent.click(within(dialog).getByRole("button", { name: "Go live" }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("The mode could not be changed. Try again.");
    expect(alert).not.toHaveTextContent("server wording");
  });

  it("forgets the last refusal when the dialog is opened again", async () => {
    serve({ mode: "SIMULATION", brake: false, refuse: refusal("MODE_LIVE_NEEDS_TRADE_KEY") });
    renderAt(<ModeBadge />);
    const first = await openDialog(/Mode: Simulation/);
    fireEvent.click(within(first).getByRole("button", { name: "Go live" }));
    await within(first).findByRole("alert");
    fireEvent.click(within(first).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    const second = await openDialog(/Mode: Simulation/);

    expect(within(second).queryByRole("alert")).not.toBeInTheDocument();
  });
});
