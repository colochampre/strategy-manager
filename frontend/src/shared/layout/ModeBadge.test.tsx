import { fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ModeBadge } from "@/shared/layout/ModeBadge";
import i18n from "@/shared/i18n";
import { jsonResponse, renderAt, SIGNED_UP, stubApi, unlock } from "@/test/harness";

const HEALTH = { kind: "ok", body: { status: "ok", dry_run: false } } as const;

function serve(mode: "LIVE" | "SIMULATION", brake: boolean) {
  return stubApi(HEALTH, [], undefined, {}, (url) =>
    url.endsWith("/api/me")
      ? Promise.resolve(
          jsonResponse({ email: "owner@example.com", is_admin: true, mode, dry_run_brake: brake, ...SIGNED_UP }),
        )
      : undefined,
  );
}

beforeEach(() => {
  unlock();
});

afterEach(async () => {
  vi.unstubAllGlobals();
  await i18n.changeLanguage("en");
});

/** The badge's own element: the status that holds the word and the dot. */
async function badge(text: string): Promise<HTMLElement> {
  const word = await screen.findByText(text);
  return word.closest('[role="status"]') as HTMLElement;
}

describe("what the badge says (L12: it only shows the mode)", () => {
  it("says Live in sentence case, tinted in the gain colour with a dot, as the prototype's .badge-live", async () => {
    serve("LIVE", false);
    renderAt(<ModeBadge />);

    const live = await badge("Live");
    expect(live).toHaveClass("h-9", "rounded-lg", "border-gain/45", "bg-gain/12", "text-gain-bright", "font-medium");
    expect(live).not.toHaveClass("uppercase");
    expect(live.querySelector('[data-dot="true"]')).toHaveClass("bg-gain", "rounded-full");
    expect(live.textContent).toBe("Live");
  });

  it("says En vivo in Spanish, not EN VIVO", async () => {
    await i18n.changeLanguage("es");
    serve("LIVE", false);
    renderAt(<ModeBadge />);

    const live = await badge("En vivo");
    expect(live.textContent).toBe("En vivo");
    expect(live).not.toHaveClass("uppercase");
  });

  it("says Simulation in the same shape, neutral and not amber: it is a state, not a decision", async () => {
    serve("SIMULATION", false);
    renderAt(<ModeBadge />);

    const simulation = await badge("Simulation");
    expect(simulation).toHaveClass("h-9", "rounded-lg", "text-ink-2");
    expect(simulation.outerHTML).not.toMatch(/-decision\b/);
    expect(simulation.querySelector('[data-dot="true"]')).toHaveClass("bg-ink-3");
  });

  it("has no menu and no button, whatever the mode: the mode is changed from My account", async () => {
    serve("LIVE", false);
    renderAt(<ModeBadge />);

    await badge("Live");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Live"));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it.each(["SIMULATION", "LIVE"] as const)(
    "says simulation is forced for everyone when the brake is on, in the amber that needs a decision (user in %s)",
    async (mode) => {
      serve(mode, true);
      renderAt(<ModeBadge />);

      const forced = await badge("Simulation forced");
      expect(forced).toHaveClass("h-9", "rounded-lg", "text-decision", "border-decision/45", "bg-decision/12");
      // Why, behind an (i) right of the badge, shown on hover and focus, below it (L.10).
      expect(forced).not.toHaveAttribute("title");
      const info = screen.getByRole("img", { name: "About the brake" });
      expect(forced.parentElement).toContainElement(info);
      expect(screen.queryByRole("tooltip")).toBeNull();
      fireEvent.mouseEnter(info.parentElement as HTMLElement);
      const tip = screen.getByRole("tooltip");
      expect(tip).toHaveTextContent("The server's brake is on: nobody trades live, so no capital is shown.");
      expect(tip).toHaveClass("top-full");
      expect(screen.queryByRole("button")).not.toBeInTheDocument();
      expect(screen.queryByText("Live")).not.toBeInTheDocument();
    },
  );

  it("draws no (i) while the brake is off (L.10)", async () => {
    serve("LIVE", false);
    renderAt(<ModeBadge />);

    await badge("Live");
    expect(screen.queryByRole("img", { name: "About the brake" })).toBeNull();
  });

  it("stays neutral while it is asked, never Live", () => {
    stubApi(HEALTH, [], undefined, {}, (url) =>
      url.endsWith("/api/me") ? new Promise<Response>(() => undefined) : undefined,
    );
    renderAt(<ModeBadge />);

    expect(screen.getByText("Checking mode").closest('[role="status"]')).toHaveClass("text-ink-3");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it.each([
    ["the network fails", () => Promise.reject(new TypeError("offline"))],
    ["a 500", () => Promise.resolve(jsonResponse({}, 500))],
    ["a body with no mode", () => Promise.resolve(jsonResponse({ email: "a@b.c", is_admin: true, dry_run_brake: false, ...SIGNED_UP }))],
  ])("says Mode unknown, never Live, on %s", async (_name, answer) => {
    stubApi(HEALTH, [], undefined, {}, (url) => (url.endsWith("/api/me") ? answer() : undefined));
    renderAt(<ModeBadge />);

    expect((await badge("Mode unknown"))).toHaveClass("text-ink-3");
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
