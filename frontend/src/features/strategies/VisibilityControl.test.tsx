import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StrategyDetailPage } from "@/features/strategies/StrategyDetailPage";
import i18n from "@/shared/i18n";
import { jsonResponse, lock, renderAt, resetExchangeScope, stubApi, strategyRoute, unlock } from "@/test/harness";

const ID = "11111111-1111-4111-8111-111111111111";
const HEALTH = { kind: "ok", body: { status: "ok", dry_run: true } } as const;
const ARCHIVED_AT = "2026-10-01T00:00:00Z";

interface Patch {
  url: string;
  body: Record<string, unknown>;
}

/**
 * The strategy's page with a stored state. A PATCH is recorded and answered by `outcome`: a refusal, or
 * `"saved"`, which stores the visibility asked for and answers the strategy as stored. Every other route is
 * the harness's.
 */
function setup(stored: Record<string, unknown>, outcome: Response | "saved" = jsonResponse({}, 500)) {
  const patches: Patch[] = [];
  let current = { ...stored };
  const detail = (url: string, init?: RequestInit) => strategyRoute(ID, "ETH Breakout", current)(url, init);
  stubApi(HEALTH, [], undefined, {}, (url, init) => {
    if (init?.method === "PATCH" && url.endsWith(`/strategies/${ID}`)) {
      patches.push({ url, body: JSON.parse(String(init.body)) as Record<string, unknown> });
      if (outcome !== "saved") return Promise.resolve(outcome);
      current = { ...current, ...patches[patches.length - 1]?.body };
      return detail(url);
    }
    return detail(url, init);
  });
  renderAt(
    <Routes>
      <Route path="strategies/:strategyId" element={<StrategyDetailPage />} />
    </Routes>,
    `/strategies/${ID}`,
  );
  return { patches };
}

const field = () => screen.findByLabelText("Visibility") as Promise<HTMLSelectElement>;

beforeEach(() => {
  unlock();
  resetExchangeScope();
});
afterEach(async () => {
  vi.unstubAllGlobals();
  lock();
  await act(() => i18n.changeLanguage("en"));
});

describe("the visibility of a strategy, on its page", () => {
  it.each([
    ["PRIVATE", "Private"],
    ["PUBLIC", "Public"],
  ])("shows the stored visibility %s as %s", async (stored, shown) => {
    setup({ visibility: stored });

    const select = await field();

    expect(select.value).toBe(stored);
    expect(within(select).getByRole("option", { name: shown })).toHaveProperty("selected", true);
    expect(within(select).getAllByRole("option")).toHaveLength(2);
    expect(select).toBeEnabled();
  });

  it("says what private means, in the settings of the strategy", async () => {
    setup({ visibility: "PRIVATE" });

    const select = await field();

    expect(select.closest("aside")).not.toBeNull();
    expect(screen.getByText("Other users cannot subscribe to a private strategy. Subscribers it already has keep it.")).toBeInTheDocument();
  });

  it("sends only the visibility when it is changed, and shows the one the server stored", async () => {
    const { patches } = setup({ visibility: "PRIVATE" }, "saved");
    const select = await field();

    fireEvent.change(select, { target: { value: "PUBLIC" } });

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]?.body).toEqual({ visibility: "PUBLIC" });
    await waitFor(() => expect((screen.getByLabelText("Visibility") as HTMLSelectElement).value).toBe("PUBLIC"));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each([
    [
      "an archived strategy (409)",
      jsonResponse({ detail: { error: "STRATEGY_ARCHIVED", message: "archived" } }, 409),
      "This strategy is archived and can no longer be changed.",
    ],
    ["a strategy that is gone (404)", jsonResponse({ detail: "Not Found" }, 404), "This strategy no longer exists."],
    ["a server error", jsonResponse({ detail: "boom" }, 500), "The visibility was not saved. Try again."],
  ])("says why after %s, and keeps showing the stored visibility", async (_name, refusal, text) => {
    const { patches } = setup({ visibility: "PRIVATE" }, refusal);
    const select = await field();

    fireEvent.change(select, { target: { value: "PUBLIC" } });

    expect(await screen.findByRole("alert")).toHaveTextContent(text);
    expect(patches).toHaveLength(1);
    await waitFor(() => expect((screen.getByLabelText("Visibility") as HTMLSelectElement).value).toBe("PRIVATE"));
  });

  it("cannot be changed on an archived strategy, and sends nothing", async () => {
    const { patches } = setup({ visibility: "PUBLIC", archived_at: ARCHIVED_AT });

    const select = await field();
    fireEvent.change(select, { target: { value: "PRIVATE" } });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 30));
    });

    expect(select).toBeDisabled();
    expect(select.value).toBe("PUBLIC");
    expect(patches).toEqual([]);
  });

  it("renders its texts in Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    setup({ visibility: "PRIVATE" });

    const select = (await screen.findByLabelText("Visibilidad")) as HTMLSelectElement;

    expect(within(select).getByRole("option", { name: "Privada" })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "Pública" })).toBeInTheDocument();
    expect(
      screen.getByText("Otros usuarios no pueden suscribirse a una estrategia privada. Los suscriptores que ya tiene la conservan."),
    ).toBeInTheDocument();
  });
});
