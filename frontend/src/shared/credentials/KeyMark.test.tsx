import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import { KeyMark } from "@/shared/credentials/KeyMark";
import type { KeyMarkSpec } from "@/shared/credentials/key-state";
import i18n from "@/shared/i18n";

const READ_ONLY: KeyMarkSpec = { word: "readOnly", tone: "amber" };
const NO_KEY_AMBER: KeyMarkSpec = { word: "noKey", tone: "amber" };
const NO_KEY_GREY: KeyMarkSpec = { word: "noKey", tone: "neutral" };

afterEach(async () => {
  await i18n.changeLanguage("en");
});

/** The element holding a text. A missing one fails here as an assertion, not as a query error. */
function markNode(text: string): HTMLElement {
  const node = screen.queryByText(text);
  expect(node, text).toBeInTheDocument();
  return node as HTMLElement;
}

describe("the words of a mark", () => {
  it.each([
    ["en", READ_ONLY, "read-only"],
    ["en", NO_KEY_AMBER, "no key"],
    ["en", NO_KEY_GREY, "no key"],
    ["es", READ_ONLY, "solo lectura"],
    ["es", NO_KEY_AMBER, "sin clave"],
    ["es", NO_KEY_GREY, "sin clave"],
  ] as const)("in %s a %j is the text %s", async (language, mark, text) => {
    await i18n.changeLanguage(language);
    render(<KeyMark mark={mark} variant="tab" />);
    expect(markNode(text)).toBeInTheDocument();
  });
});

describe("a mark on a tab is plain text", () => {
  it("is amber with text-decision and grey with text-ink-3", () => {
    const { rerender } = render(<KeyMark mark={READ_ONLY} variant="tab" />);
    expect(markNode("read-only")).toHaveClass("text-decision");
    expect(markNode("read-only")).not.toHaveClass("text-ink-3");

    rerender(<KeyMark mark={NO_KEY_GREY} variant="tab" />);
    expect(markNode("no key")).toHaveClass("text-ink-3");
    expect(markNode("no key")).not.toHaveClass("text-decision");
  });

  it("carries the tab type and the caller's own classes, and no border", () => {
    render(<KeyMark mark={NO_KEY_AMBER} variant="tab" className="row-start-3 self-start" />);
    const mark = markNode("no key");
    expect(mark).toHaveClass("font-mono", "text-[11px]", "leading-3.5", "whitespace-nowrap");
    expect(mark).toHaveClass("row-start-3", "self-start");
    expect(mark).not.toHaveClass("border");
    expect(mark).not.toHaveClass("rounded");
  });
});

describe("a mark on a card is a tag", () => {
  const TAG = ["whitespace-nowrap", "rounded", "border", "px-2", "py-0.5", "font-mono", "text-xs"];

  it("is amber with a solid amber border", () => {
    render(<KeyMark mark={READ_ONLY} variant="tag" />);
    const tag = markNode("read-only");
    expect(tag).toHaveClass(...TAG, "border-decision", "text-decision");
    expect(tag).not.toHaveClass("border-dashed");
  });

  it("is grey with a solid grey border", () => {
    render(<KeyMark mark={NO_KEY_GREY} variant="tag" />);
    const tag = markNode("no key");
    expect(tag).toHaveClass(...TAG, "border-rule-strong", "text-ink-3");
    expect(tag).not.toHaveClass("border-dashed");
    expect(tag).not.toHaveClass("text-decision");
    expect(tag).not.toHaveClass("border-decision");
  });

  it("is the element the caller asks for, a list item inside a list", () => {
    render(
      <ul>
        <KeyMark mark={READ_ONLY} variant="tag" as="li" />
      </ul>,
    );
    expect(screen.queryByRole("listitem")).toHaveTextContent("read-only");
  });
});

describe("a mark is never drawn with a hex colour, var() or a style", () => {
  it("has none in its classes or its markup", () => {
    for (const variant of ["tab", "tag"] as const) {
      const { container, unmount } = render(<KeyMark mark={READ_ONLY} variant={variant} className="row-start-3" />);
      const html = container.innerHTML;
      expect(html, variant).toContain("read-only");
      expect(html, variant).not.toMatch(/#[0-9a-fA-F]{3,8}|var\(/);
      expect(html, variant).not.toContain("style=");
      unmount();
    }
  });

  it("has none in its source", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const source = readFileSync(join(here, "KeyMark.tsx"), "utf8");
    expect(source.length).toBeGreaterThan(100);
    expect(source).not.toMatch(/#[0-9a-fA-F]{3,8}\b|var\(|style=/);
  });
});
