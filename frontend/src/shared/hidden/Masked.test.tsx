import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HIDDEN_STORAGE_KEY, useHiddenStore } from "@/shared/hidden/hidden-store";
import { Masked } from "@/shared/hidden/Masked";
import i18n from "@/shared/i18n";

beforeEach(async () => {
  window.localStorage.clear();
  useHiddenStore.setState({ hidden: false });
  await act(() => i18n.changeLanguage("en"));
});

describe("the hidden store (S1)", () => {
  it("starts with the balances shown", () => {
    expect(useHiddenStore.getState().hidden).toBe(false);
  });

  it("toggles and persists the choice under sm.hidden, in the browser only", () => {
    useHiddenStore.getState().toggle();

    expect(useHiddenStore.getState().hidden).toBe(true);
    expect(HIDDEN_STORAGE_KEY).toBe("sm.hidden");
    expect(JSON.parse(window.localStorage.getItem("sm.hidden") as string).state.hidden).toBe(true);

    useHiddenStore.getState().toggle();
    expect(useHiddenStore.getState().hidden).toBe(false);
  });

  it("reads a stored choice back after a reload", async () => {
    window.localStorage.setItem("sm.hidden", JSON.stringify({ state: { hidden: true }, version: 0 }));

    await useHiddenStore.persist.rehydrate();

    expect(useHiddenStore.getState().hidden).toBe(true);
  });

  it.each([
    ["a wrong type", { hidden: "yes" }],
    ["a missing field", {}],
    ["a null", { hidden: null }],
  ])("reads %s from storage as shown", async (_label, state) => {
    useHiddenStore.setState({ hidden: true });
    window.localStorage.setItem("sm.hidden", JSON.stringify({ state, version: 0 }));

    await useHiddenStore.persist.rehydrate();

    expect(useHiddenStore.getState().hidden).toBe(false);
  });

  it("degrades to memory when localStorage throws (private mode)", () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    expect(() => useHiddenStore.getState().toggle()).not.toThrow();
    expect(useHiddenStore.getState().hidden).toBe(true);
    setItemSpy.mockRestore();
  });
});

describe("Masked", () => {
  it("draws its figure while the balances are shown", () => {
    render(<Masked>1,284.52</Masked>);

    expect(screen.getByText("1,284.52")).toBeInTheDocument();
    expect(screen.queryByText("******")).not.toBeInTheDocument();
  });

  it("draws six stars and no figure while hidden, and names them for a screen reader", () => {
    useHiddenStore.setState({ hidden: true });
    render(<Masked>1,284.52</Masked>);

    expect(screen.getByText("******")).toBeInTheDocument();
    expect(screen.queryByText("1,284.52")).not.toBeInTheDocument();
    // An image named "Hidden": a screen reader does not read the stars.
    expect(screen.getByRole("img", { name: "Hidden" })).toHaveTextContent("******");
  });

  it("names them in Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    useHiddenStore.setState({ hidden: true });
    render(<Masked>1,284.52</Masked>);

    expect(screen.getByRole("img", { name: "Oculto" })).toBeInTheDocument();
  });

  it("follows the store without a reload", () => {
    render(<Masked>1,284.52</Masked>);
    expect(screen.getByText("1,284.52")).toBeInTheDocument();

    act(() => useHiddenStore.getState().toggle());

    expect(screen.queryByText("1,284.52")).not.toBeInTheDocument();
    expect(screen.getByText("******")).toBeInTheDocument();
  });
});
