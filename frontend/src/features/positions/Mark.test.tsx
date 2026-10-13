import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Mark } from "@/features/positions/Mark";
import type { MarkOrigin, MarkProps } from "@/features/positions/Mark";
import en from "@/shared/i18n/locales/en.json";

/** The rule of design § H (T16): shape says what a mark is, colour says the origin, red says something is wrong. */
const COLOURS: Record<MarkOrigin, { border: string; text: string; word: string }> = {
  rehearsal: { border: "border-decision", text: "text-decision", word: en.positions.origin.rehearsal },
  live: { border: "border-gain", text: "text-gain", word: en.positions.origin.live },
  mixed: { border: "border-loss", text: "text-loss", word: en.positions.origin.mixed },
  unknown: { border: "border-rule-strong", text: "text-ink-3", word: en.positions.origin.unknown },
};

const POSITIONS: MarkProps[] = (["rehearsal", "live", "mixed", "unknown"] as const).map((origin) => ({
  kind: "position",
  origin,
  pair: "AAVEUSDT",
  side: "LONG",
}));
const ORDERS: MarkProps[] = (["rehearsal", "live", "unknown"] as const).map((origin) => ({
  kind: "order",
  origin,
  pair: "AAVEUSDT",
}));
const VENUE: MarkProps = { kind: "venue" };

function label(props: MarkProps): string {
  return props.kind === "venue" ? "venue" : `${props.kind}, ${props.origin}`;
}

function drawn(props: MarkProps): HTMLElement {
  const { container } = render(<Mark {...props} />);
  return container.firstElementChild as HTMLElement;
}

describe("a position mark", () => {
  it.each(POSITIONS.map((props) => [label(props), props] as const))("%s is filled with a solid border", (_label, props) => {
    const mark = drawn(props);

    expect(mark).toHaveClass("bg-panel-2");
    expect(mark).not.toHaveClass("border-dashed");
    expect(mark).not.toHaveClass("bg-transparent");
  });
});

describe("an order mark", () => {
  it.each(ORDERS.map((props) => [label(props), props] as const))("%s is unfilled with a dashed border", (_label, props) => {
    const mark = drawn(props);

    expect(mark).toHaveClass("border-dashed");
    expect(mark).toHaveClass("bg-transparent");
    expect(mark).not.toHaveClass("bg-panel-2");
  });
});

describe("dashed means an order in flight and nothing else", () => {
  it.each([...POSITIONS, VENUE].map((props) => [label(props), props] as const))("%s has no dashed border", (_label, props) => {
    const mark = drawn(props);

    expect(mark.className).not.toContain("border-dashed");
    expect(mark.querySelector(".border-dashed")).toBeNull();
  });
});

describe("the colour says the origin", () => {
  it.each([...POSITIONS, ...ORDERS].map((props) => [label(props), props] as const))(
    "%s has the border and the word of its origin",
    (_label, props) => {
      if (props.kind === "venue") throw new Error("not an origin mark");
      const colours = COLOURS[props.origin];
      const mark = drawn(props);

      expect(mark).toHaveClass(colours.border);
      const word = screen.getByText(colours.word);
      expect(word).toHaveClass(colours.text);
    },
  );
});

describe("red means something is wrong and nothing else", () => {
  const redOf = (mark: HTMLElement) => mark.className.split(/\s+/).some((name) => name === "border-loss" || name === "text-loss") ||
    mark.querySelector(".border-loss, .text-loss") !== null;

  it("is on the position of both origins, with its words", () => {
    const mark = drawn({ kind: "position", origin: "mixed", pair: "STXUSDT", side: "LONG" });

    expect(mark).toHaveClass("border-loss");
    expect(screen.getByText(en.positions.origin.mixed)).toHaveClass("text-loss");
  });

  it("is on the venue chip, with its words", () => {
    const mark = drawn(VENUE);

    expect(mark).toHaveClass("border-loss");
    expect(mark).toHaveClass("text-loss");
    expect(mark).toHaveClass("bg-transparent");
    expect(mark).toHaveTextContent(en.positions.venue.disagrees);
  });

  it.each(
    [...POSITIONS, ...ORDERS]
      .filter((props) => props.kind !== "venue" && props.origin !== "mixed")
      .map((props) => [label(props), props] as const),
  )("is on no other mark: %s", (_label, props) => {
    expect(redOf(drawn(props))).toBe(false);
  });
});

describe("what a chip reads", () => {
  it("holds the pair, the side in ink, then the origin, for a position", () => {
    const mark = drawn({ kind: "position", origin: "live", pair: "AAVEUSDT", side: "LONG" });

    expect(mark).toHaveTextContent("AAVEUSDT · LONG · Live");
    const side = screen.getByText("LONG");
    expect(side.className).not.toMatch(/text-(gain|loss|decision)/);
    expect(mark).toHaveClass("text-ink");
  });

  it("keeps SHORT in ink as well", () => {
    drawn({ kind: "position", origin: "rehearsal", pair: "SFPUSDT", side: "SHORT" });

    expect(screen.getByText("SHORT").className).not.toMatch(/text-(gain|loss|decision)/);
  });

  it("says that the side is not readable when it is null", () => {
    const mark = drawn({ kind: "position", origin: "live", pair: "XYZBTC", side: null });

    expect(mark).toHaveTextContent("XYZBTC · side not readable · Live");
  });

  it("holds the pair, 'order in flight' and the origin, for an order", () => {
    const mark = drawn({ kind: "order", origin: "unknown", pair: "STXUSDT" });

    expect(mark).toHaveTextContent("STXUSDT · order in flight · origin unknown");
  });

  it("draws its separators in the faint ink", () => {
    drawn({ kind: "position", origin: "live", pair: "AAVEUSDT", side: "LONG" });

    const separators = screen.getAllByText("·");
    expect(separators).toHaveLength(2);
    for (const separator of separators) expect(separator).toHaveClass("text-ink-3");
  });

  it("shares one base: mono, 12 px, one line, a 1 px border", () => {
    for (const props of [...POSITIONS, ...ORDERS, VENUE]) {
      const mark = drawn(props);
      expect(mark, label(props)).toHaveClass("font-mono", "text-xs", "border", "whitespace-nowrap");
      document.body.innerHTML = "";
    }
  });
});
