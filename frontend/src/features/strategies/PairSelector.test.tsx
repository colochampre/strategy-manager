import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PairSelector } from "@/features/strategies/PairSelector";
import type { PairSelectorProps } from "@/features/strategies/PairSelector";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";

/** Every `strategies.pairs.*` key the selector renders. The test below holds this list to en and es. */
const KEYS = [
  "search",
  "choosePool",
  "loading",
  "loadFailed",
  "retry",
  "noMatch",
  "showing",
  "narrow",
  "remove",
  "notListed",
  "selected",
] as const;

/** The text of a key in the active language; a missing key reads as the key itself, so a test fails on text. */
function copy(key: (typeof KEYS)[number], values: Record<string, string | number> = {}): string {
  return i18n.t(`strategies.pairs.${key}`, values);
}

/** A value of a locale file by its dotted path, `undefined` when any part is missing. */
function lookup(tree: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], tree);
}

const LABEL = "Allowed pairs";
const LISTED = ["AAVEUSDT", "SFPUSDT", "STXUSDT"];

function selector(overrides: Partial<PairSelectorProps> = {}) {
  const props: PairSelectorProps = {
    id: "pairs",
    label: LABEL,
    value: [],
    onChange: vi.fn(),
    options: LISTED,
    status: "ready",
    onRetry: vi.fn(),
    ...overrides,
  };
  return { props, ...render(<PairSelector {...props} />) };
}

function search(): HTMLInputElement {
  return screen.getByRole("searchbox", { name: copy("search") });
}

function type(text: string) {
  fireEvent.change(search(), { target: { value: text } });
}

function optionNames(): string[] {
  return screen.queryAllByRole("checkbox").map((box) => box.closest("label")?.textContent ?? "");
}

function manyOptions(count: number): string[] {
  return Array.from({ length: count }, (_, index) => `T${String(index).padStart(3, "0")}USDT`);
}

afterEach(async () => {
  await act(() => i18n.changeLanguage("en"));
});

describe("PairSelector", () => {
  it("idle shows choose-a-pool and a disabled search field", () => {
    selector({ status: "idle", options: undefined });

    expect(screen.getByText(copy("choosePool"))).toBeInTheDocument();
    expect(search()).toBeDisabled();
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
  });

  it("loading shows a status line and no option", () => {
    selector({ status: "loading", options: undefined });

    expect(screen.getByRole("status")).toHaveTextContent(copy("loading"));
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(search()).toBeDisabled();
  });

  it("error shows an alert and a retry control that calls onRetry", () => {
    const { props } = selector({ status: "error", options: undefined });

    expect(screen.getByRole("alert")).toHaveTextContent(copy("loadFailed"));
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: copy("retry") }));

    expect(props.onRetry).toHaveBeenCalledTimes(1);
  });

  it("ready offers every listed pair as a checkbox", () => {
    selector();

    expect(optionNames()).toEqual(LISTED);
    expect(search()).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("typing another spelling finds the pair", () => {
    selector();

    type("stxusdt.p");
    expect(optionNames()).toEqual(["STXUSDT"]);

    type("sfpusdt_perp");
    expect(optionNames()).toEqual(["SFPUSDT"]);

    type("usdt");
    expect(optionNames()).toEqual(LISTED);

    type("  sfp ");
    expect(optionNames()).toEqual(["SFPUSDT"]);
  });

  it("toggling an option with the keyboard calls onChange with the pair", () => {
    const { props } = selector({ value: ["AAVEUSDT"] });

    const box = screen.getByRole("checkbox", { name: "STXUSDT" });
    box.focus();
    // A native checkbox is in the tab order and Space clicks it; jsdom does not turn Space into a click.
    expect(box).toHaveFocus();
    expect(box).toHaveAttribute("type", "checkbox");
    fireEvent.click(box);

    expect(props.onChange).toHaveBeenLastCalledWith(["AAVEUSDT", "STXUSDT"]);
  });

  it("unchecking a selected option removes only that pair", () => {
    const { props } = selector({ value: ["AAVEUSDT", "STXUSDT"] });

    expect(screen.getByRole("checkbox", { name: "AAVEUSDT" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "SFPUSDT" })).not.toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: "AAVEUSDT" }));

    expect(props.onChange).toHaveBeenLastCalledWith(["STXUSDT"]);
  });

  it("every selected pair has a remove control labelled with its symbol", () => {
    const { props } = selector({ value: ["STXUSDT", "AAVEUSDT"] });

    const chips = within(screen.getByRole("list", { name: copy("selected") })).getAllByRole("listitem");
    expect(chips.map((chip) => chip.textContent)).toEqual([
      expect.stringContaining("STXUSDT"),
      expect.stringContaining("AAVEUSDT"),
    ]);
    const remove = screen.getByRole("button", { name: copy("remove", { symbol: "STXUSDT" }) });
    expect(screen.getByRole("button", { name: copy("remove", { symbol: "AAVEUSDT" }) })).toBeInTheDocument();
    fireEvent.click(remove);

    expect(props.onChange).toHaveBeenLastCalledWith(["AAVEUSDT"]);
  });

  it("more than fifty matches renders fifty and says how many match", () => {
    selector({ options: manyOptions(120) });

    expect(optionNames()).toHaveLength(50);
    expect(optionNames()[0]).toBe("T000USDT");
    expect(optionNames()[49]).toBe("T049USDT");
    expect(screen.getByText(copy("showing", { shown: 50, total: 120 }))).toBeInTheDocument();
    expect(screen.getByText(copy("narrow"))).toBeInTheDocument();

    type("t01");
    expect(optionNames()).toHaveLength(10);
    expect(screen.getByText(copy("showing", { shown: 10, total: 10 }))).toBeInTheDocument();
    expect(screen.queryByText(copy("narrow"))).not.toBeInTheDocument();
  });

  it("exactly fifty matches are all rendered", () => {
    selector({ options: manyOptions(50) });

    expect(optionNames()).toHaveLength(50);
    expect(screen.getByText(copy("showing", { shown: 50, total: 50 }))).toBeInTheDocument();
  });

  it("announces the count in a polite live region", () => {
    const { container } = selector({ options: manyOptions(120) });

    const live = container.querySelector('[aria-live="polite"]');
    expect(live).toHaveTextContent(copy("showing", { shown: 50, total: 120 }));
  });

  it("no match says so", () => {
    const { container } = selector();

    type("zzz");

    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(screen.getByText(copy("noMatch"))).toBeInTheDocument();
    expect(container.querySelector('[aria-live="polite"]')).toHaveTextContent(copy("noMatch"));
  });

  it("a selected pair missing from the options is kept and marked no longer listed", () => {
    const { props } = selector({ value: ["SFPUSDT", "STXUSDT"], options: ["AAVEUSDT", "STXUSDT"] });

    const chips = within(screen.getByRole("list", { name: copy("selected") })).getAllByRole("listitem");
    expect(chips).toHaveLength(2);
    expect(chips[0]).toHaveTextContent("SFPUSDT");
    expect(chips[0]).toHaveTextContent(copy("notListed"));
    expect(chips[1]).toHaveTextContent("STXUSDT");
    expect(chips[1]).not.toHaveTextContent(copy("notListed"));
    expect(props.onChange).not.toHaveBeenCalled();

    // It stays in the value while another pair is toggled, and leaves only when the operator removes it.
    fireEvent.click(screen.getByRole("checkbox", { name: "AAVEUSDT" }));
    expect(props.onChange).toHaveBeenLastCalledWith(["SFPUSDT", "STXUSDT", "AAVEUSDT"]);
    fireEvent.click(screen.getByRole("button", { name: copy("remove", { symbol: "SFPUSDT" }) }));
    expect(props.onChange).toHaveBeenLastCalledWith(["STXUSDT"]);
  });

  it("a delisted pair is not offered again once it is no longer selected", () => {
    selector({ value: [], options: ["AAVEUSDT", "STXUSDT"] });

    expect(optionNames()).toEqual(["AAVEUSDT", "STXUSDT"]);
    expect(screen.queryByText(copy("notListed"))).not.toBeInTheDocument();
  });

  it("does not call a pair no longer listed while the options are not known", () => {
    selector({ value: ["SFPUSDT"], status: "loading", options: undefined });

    const chip = within(screen.getByRole("list", { name: copy("selected") })).getByRole("listitem");
    expect(chip).toHaveTextContent("SFPUSDT");
    expect(chip).not.toHaveTextContent(copy("notListed"));
  });

  it("selected pairs stay removable in the error state", () => {
    const { props } = selector({ status: "error", options: undefined, value: ["SFPUSDT", "STXUSDT"] });

    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: copy("remove", { symbol: "SFPUSDT" }) }));

    expect(props.onChange).toHaveBeenLastCalledWith(["STXUSDT"]);
  });

  it("selected pairs stay listed while idle and loading", () => {
    selector({ status: "idle", options: undefined, value: ["STXUSDT"] });

    expect(screen.getByRole("button", { name: copy("remove", { symbol: "STXUSDT" }) })).toBeInTheDocument();
  });

  it("the search field, every option and every remove control have an accessible name", () => {
    selector({ value: ["STXUSDT", "SFPUSDT"], options: ["AAVEUSDT", "STXUSDT"] });

    expect(screen.getByRole("group", { name: LABEL })).toBeInTheDocument();
    expect(search()).toHaveAccessibleName(copy("search"));
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(2);
    for (const box of boxes) expect(box).toHaveAccessibleName(/\S/);
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(2);
    for (const button of buttons) {
      expect(button).toHaveAccessibleName(/\S/);
      expect(button).toHaveAttribute("type", "button");
    }
  });

  it("forwards describedBy to the group", () => {
    selector({ describedBy: "pairs-hint" });

    expect(screen.getByRole("group", { name: LABEL })).toHaveAttribute("aria-describedby", "pairs-hint");
  });

  it("disables every control when disabled", () => {
    selector({ disabled: true, value: ["STXUSDT"] });

    expect(search()).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "AAVEUSDT" })).toBeDisabled();
    expect(screen.getByRole("button", { name: copy("remove", { symbol: "STXUSDT" }) })).toBeDisabled();
  });

  it("pressing Enter in the search field never submits an enclosing form", () => {
    render(
      <form onSubmit={(event) => event.preventDefault()}>
        <PairSelector id="pairs" label={LABEL} value={[]} onChange={vi.fn()} options={LISTED} status="ready" onRetry={vi.fn()} />
      </form>,
    );

    expect(fireEvent.keyDown(search(), { key: "Enter" })).toBe(false);
    expect(fireEvent.keyDown(search(), { key: "a" })).toBe(true);
  });

  it("renders its texts in Spanish", async () => {
    await act(() => i18n.changeLanguage("es"));
    selector({ status: "idle", options: undefined, value: ["STXUSDT"] });

    const choosePool = lookup(es, "strategies.pairs.choosePool");
    const remove = lookup(es, "strategies.pairs.remove");
    expect(choosePool).toEqual(expect.stringMatching(/\S/));
    expect(screen.getByText(String(choosePool))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: String(remove).replace("{{symbol}}", "STXUSDT") })).toBeInTheDocument();
  });

  it("every key exists in en and es", () => {
    const placeholders = (text: unknown) => String(text).match(/{{\w+}}/g)?.sort() ?? [];

    for (const key of KEYS) {
      const path = `strategies.pairs.${key}`;
      const english = lookup(en, path);
      const spanish = lookup(es, path);
      expect(english, `en ${path}`).toEqual(expect.stringMatching(/\S/));
      expect(spanish, `es ${path}`).toEqual(expect.stringMatching(/\S/));
      expect(placeholders(spanish), `placeholders of ${path}`).toEqual(placeholders(english));
    }
  });
});
