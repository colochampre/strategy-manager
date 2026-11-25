import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ModeSection } from "@/features/settings/ModeSection";
import { CONFIRMED_KEY, useConfirmedDiscrepancies } from "@/shared/api/discrepancies";
import i18n from "@/shared/i18n";
import { jsonResponse, renderAt, SIGNED_UP, stubApi, unlock } from "@/test/harness";

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
        jsonResponse({ email: "owner@example.com", is_admin: true, mode: server.mode, dry_run_brake: server.brake, ...SIGNED_UP }),
      );
    }
    if (!url.endsWith("/api/me/mode")) return undefined;
    if (server.hold !== undefined) return server.hold;
    if (server.refuse !== undefined) return Promise.resolve(server.refuse());
    server.mode = (JSON.parse(String(init?.body)) as { mode: Server["mode"] }).mode;
    return Promise.resolve(
      jsonResponse({ email: "owner@example.com", is_admin: true, mode: server.mode, dry_run_brake: server.brake, ...SIGNED_UP }),
    );
  });
}

function posts(fetchMock: ReturnType<typeof stubApi>) {
  return fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/me/mode"));
}

function refusal(error: string, symbols: string[] = []) {
  return () => jsonResponse({ detail: { error, message: "server wording", symbols } }, 409);
}

/** The switch's option for a mode, once the mode is read. */
async function option(name: "Live" | "Simulation") {
  return screen.findByRole("radio", { name });
}

/** Presses the option that is not in force: the one that asks for a confirmation. */
async function openDialog(target: "Live" | "Simulation") {
  fireEvent.click(await option(target));
  return screen.findByRole("dialog");
}

beforeEach(() => {
  unlock();
});

afterEach(async () => {
  vi.unstubAllGlobals();
  await i18n.changeLanguage("en");
});

describe("the Mode card of Mi cuenta (ex7)", () => {
  it("is a card titled Mode with its sentence and a switch of Live and Simulation, the mode in force checked", async () => {
    serve({ mode: "SIMULATION", brake: false });
    renderAt(<ModeSection />);

    expect(await screen.findByRole("heading", { level: 2, name: "Mode" })).toBeInTheDocument();
    expect(
      await screen.findByText("Live sends real orders. Simulation records the signals without trading."),
    ).toBeInTheDocument();
    const group = screen.getByRole("radiogroup", { name: "Trading mode" });
    const options = within(group).getAllByRole("radio");
    expect(options.map((item) => [item.textContent, item.getAttribute("aria-checked")])).toEqual([
      ["Live", "false"],
      ["Simulation", "true"],
    ]);
  });

  it("checks Live when the user is live", async () => {
    serve({ mode: "LIVE", brake: false });
    renderAt(<ModeSection />);

    expect(await option("Live")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Simulation" })).toHaveAttribute("aria-checked", "false");
  });

  it("sends nothing when the option in force is pressed", async () => {
    const fetchMock = serve({ mode: "SIMULATION", brake: false });
    renderAt(<ModeSection />);

    fireEvent.click(await option("Simulation"));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts(fetchMock)).toHaveLength(0);
  });

  it("is drawn in Spanish with the prototype's words", async () => {
    await i18n.changeLanguage("es");
    serve({ mode: "SIMULATION", brake: false });
    renderAt(<ModeSection />);

    expect(await screen.findByRole("heading", { level: 2, name: "Modo" })).toBeInTheDocument();
    expect(
      await screen.findByText("En vivo envía órdenes reales. Simulación registra las señales sin operar."),
    ).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "En vivo" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Simulación" })).toBeInTheDocument();
  });
});

describe("the brake and the states the mode is not known in", () => {
  it.each(["SIMULATION", "LIVE"] as const)(
    "says simulation is forced for everyone when the brake is on, and the switch cannot be pressed (user in %s)",
    async (mode) => {
      serve({ mode, brake: true });
      renderAt(<ModeSection />);

      expect(
        await screen.findByText("The brake is on: everyone trades in simulation, so the mode cannot be changed."),
      ).toBeInTheDocument();
      const options = screen.getAllByRole("radio");
      expect(options).toHaveLength(2);
      for (const item of options) expect(item).toBeDisabled();
      expect(screen.getByRole("radio", { name: "Simulation" })).toHaveAttribute("aria-checked", "true");
      expect(screen.getByRole("radio", { name: "Live" })).toHaveAttribute("aria-checked", "false");
    },
  );

  it("draws no switch while the mode is asked, never Live", () => {
    stubApi(HEALTH, [], undefined, {}, (url) =>
      url.endsWith("/api/me") ? new Promise<Response>(() => undefined) : undefined,
    );
    renderAt(<ModeSection />);

    expect(screen.getByText("Checking mode")).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  });

  it.each([
    ["the network fails", () => Promise.reject(new TypeError("offline"))],
    ["a 500", () => Promise.resolve(jsonResponse({}, 500))],
    ["a body with no mode", () => Promise.resolve(jsonResponse({ email: "a@b.c", is_admin: true, dry_run_brake: false, ...SIGNED_UP }))],
  ])("says Mode unknown, never Live, on %s", async (_name, answer) => {
    stubApi(HEALTH, [], undefined, {}, (url) => (url.endsWith("/api/me") ? answer() : undefined));
    renderAt(<ModeSection />);

    expect(await screen.findByText("Mode unknown")).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  });
});

describe("changing the mode", () => {
  it("asks first: the click sends nothing, and Cancel has the focus", async () => {
    const fetchMock = serve({ mode: "SIMULATION", brake: false });
    renderAt(<ModeSection />);

    const dialog = await openDialog("Live");

    expect(within(dialog).getByRole("heading", { name: "Go live?" })).toBeInTheDocument();
    expect(within(dialog).getByText(REAL_ORDERS)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(posts(fetchMock)).toHaveLength(0);
  });

  it("sends nothing on Cancel", async () => {
    const fetchMock = serve({ mode: "SIMULATION", brake: false });
    renderAt(<ModeSection />);
    const dialog = await openDialog("Live");

    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posts(fetchMock)).toHaveLength(0);
    expect(screen.getByRole("radio", { name: "Simulation" })).toHaveAttribute("aria-checked", "true");
  });

  it("goes live on the dialog's own button, and the switch follows", async () => {
    const fetchMock = serve({ mode: "SIMULATION", brake: false });
    renderAt(<ModeSection />);
    const dialog = await openDialog("Live");

    fireEvent.click(within(dialog).getByRole("button", { name: "Go live" }));

    await waitFor(() => expect(screen.getByRole("radio", { name: "Live" })).toHaveAttribute("aria-checked", "true"));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posts(fetchMock)).toHaveLength(1);
    expect(JSON.parse(String(posts(fetchMock)[0]?.[1]?.body))).toEqual({ mode: "LIVE" });
  });

  it("goes back to simulation, saying no real order is placed", async () => {
    const fetchMock = serve({ mode: "LIVE", brake: false });
    renderAt(<ModeSection />);
    const dialog = await openDialog("Simulation");

    expect(
      within(dialog).getByText("Openings will be simulated against your real balance. No real order is placed for them."),
    ).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Move to simulation" }));

    await waitFor(() => expect(screen.getByRole("radio", { name: "Simulation" })).toHaveAttribute("aria-checked", "true"));
    expect(JSON.parse(String(posts(fetchMock)[0]?.[1]?.body))).toEqual({ mode: "SIMULATION" });
  });

  it("reads the discrepancies again, because whether they are compared follows the mode", async () => {
    const fetchMock = serve({ mode: "SIMULATION", brake: false });
    function Reader() {
      useConfirmedDiscrepancies();
      return <ModeSection />;
    }
    renderAt(<Reader />);
    const confirmedReads = () =>
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith(CONFIRMED_KEY.join("/"))).length;
    const dialog = await openDialog("Live");
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
    renderAt(<ModeSection />);
    const dialog = await openDialog("Live");

    fireEvent.click(within(dialog).getByRole("button", { name: "Go live" }));

    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    await waitFor(() => expect(cancel).toBeDisabled());
    expect(within(dialog).getByRole("button", { name: "Changing…" })).toBeDisabled();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    release(jsonResponse({ email: "owner@example.com", is_admin: true, mode: "LIVE", dry_run_brake: false, ...SIGNED_UP }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("closes on Escape when nothing is in flight", async () => {
    serve({ mode: "SIMULATION", brake: false });
    renderAt(<ModeSection />);
    const dialog = await openDialog("Live");

    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("each refusal in words", () => {
  it("says a key that can trade is missing, and the mode stays", async () => {
    serve({ mode: "SIMULATION", brake: false, refuse: refusal("MODE_LIVE_NEEDS_TRADE_KEY") });
    renderAt(<ModeSection />);
    const dialog = await openDialog("Live");

    fireEvent.click(within(dialog).getByRole("button", { name: "Go live" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Going live needs an active key that can trade. Add one in Link exchange.",
    );
    expect(screen.getByRole("radio", { name: "Simulation" })).toHaveAttribute("aria-checked", "true");
  });

  it("lists the symbols of a flat refusal", async () => {
    serve({ mode: "LIVE", brake: false, refuse: refusal("MODE_SIMULATION_NEEDS_FLAT", ["SFPUSDT", "STXUSDT"]) });
    renderAt(<ModeSection />);
    const dialog = await openDialog("Simulation");

    fireEvent.click(within(dialog).getByRole("button", { name: "Move to simulation" }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("Going to simulation needs nothing real held.");
    expect(within(alert).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["SFPUSDT", "STXUSDT"]);
  });

  it("says the brake is on, and keeps saying it after the switch has locked", async () => {
    const server: Server = { mode: "SIMULATION", brake: false };
    server.refuse = () => {
      server.brake = true;
      return refusal("MODE_BRAKE_ON")();
    };
    serve(server);
    renderAt(<ModeSection />);
    const dialog = await openDialog("Live");

    fireEvent.click(within(dialog).getByRole("button", { name: "Go live" }));

    await waitFor(() => expect(screen.getByRole("radio", { name: "Live" })).toBeDisabled());
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The brake is on: everyone is in simulation until it is released, so the mode cannot change.",
    );
  });

  it("says the change failed on anything else, never with the server's words", async () => {
    serve({ mode: "SIMULATION", brake: false, refuse: () => jsonResponse({ detail: "server wording" }, 500) });
    renderAt(<ModeSection />);
    const dialog = await openDialog("Live");

    fireEvent.click(within(dialog).getByRole("button", { name: "Go live" }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("The mode could not be changed. Try again.");
    expect(alert).not.toHaveTextContent("server wording");
  });

  it("forgets the last refusal when the dialog is opened again", async () => {
    serve({ mode: "SIMULATION", brake: false, refuse: refusal("MODE_LIVE_NEEDS_TRADE_KEY") });
    renderAt(<ModeSection />);
    const first = await openDialog("Live");
    fireEvent.click(within(first).getByRole("button", { name: "Go live" }));
    await within(first).findByRole("alert");
    fireEvent.click(within(first).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    const second = await openDialog("Live");

    expect(within(second).queryByRole("alert")).not.toBeInTheDocument();
  });
});
