import { describe, expect, it } from "vitest";

import { linkify } from "@/shared/lib/linkify";

const text = (t: string) => ({ kind: "text", text: t });
const link = (t: string) => ({ kind: "link", text: t });

describe("linkify", () => {
  it("returns plain text as one text segment", () => {
    expect(linkify("Trend follower.")).toEqual([text("Trend follower.")]);
  });

  it("returns nothing for an empty string", () => {
    expect(linkify("")).toEqual([]);
  });

  it("splits text around an http and an https URL", () => {
    expect(linkify("See https://example.com/a?b=1#c and http://example.org now")).toEqual([
      text("See "),
      link("https://example.com/a?b=1#c"),
      text(" and "),
      link("http://example.org"),
      text(" now"),
    ]);
  });

  it("is case-insensitive on the scheme", () => {
    expect(linkify("HTTPS://Example.com")).toEqual([link("HTTPS://Example.com")]);
  });

  it.each([".", ",", ";", ":", "!", "?"])("keeps a trailing %s outside the link", (mark) => {
    expect(linkify(`Docs at https://example.com/x${mark}`)).toEqual([text("Docs at "), link("https://example.com/x"), text(mark)]);
  });

  it("keeps several trailing marks outside the link", () => {
    expect(linkify("(see https://example.com/x).")).toEqual([text("(see "), link("https://example.com/x"), text(").")]);
    expect(linkify("https://example.com?!")).toEqual([link("https://example.com"), text("?!")]);
  });

  it("keeps a closing parenthesis that balances an opening one inside the link", () => {
    expect(linkify("https://en.wikipedia.org/wiki/Foo_(bar)")).toEqual([link("https://en.wikipedia.org/wiki/Foo_(bar)")]);
    expect(linkify("https://en.wikipedia.org/wiki/Foo_(bar).")).toEqual([link("https://en.wikipedia.org/wiki/Foo_(bar)"), text(".")]);
  });

  it("leaves an unbalanced closing parenthesis outside the link", () => {
    expect(linkify("(https://example.com/x)")).toEqual([text("("), link("https://example.com/x"), text(")")]);
  });

  it("stops a URL at whitespace and at a line break, keeping the break", () => {
    expect(linkify("a https://example.com/x\nb https://example.org/y")).toEqual([
      text("a "),
      link("https://example.com/x"),
      text("\nb "),
      link("https://example.org/y"),
    ]);
  });

  it("stops a URL at angle brackets and quotes", () => {
    expect(linkify('<https://example.com/x> "https://example.org/y"')).toEqual([
      text("<"),
      link("https://example.com/x"),
      text('> "'),
      link("https://example.org/y"),
      text('"'),
    ]);
  });

  it.each([
    "javascript:alert(1)",
    "data:text/html,<b>x</b>",
    "ftp://example.com/file",
    "www.example.com",
    "example.com",
    "mailto:a@b.c",
    "https://",
    "http:// spaced",
    "xhttps://example.com",
  ])("leaves %s as text", (value) => {
    expect(linkify(value).every((s) => s.kind === "text")).toBe(true);
  });

  it("does not link a scheme glued to a word", () => {
    expect(linkify("xhttps://example.com")).toEqual([text("xhttps://example.com")]);
  });

  it("rebuilds the input exactly from its segments", () => {
    const input = "a (https://x.io/a_(b)). Then, http://y.io; <b>z</b>\n\nwww.q.io https://";
    expect(
      linkify(input)
        .map((s) => s.text)
        .join(""),
    ).toBe(input);
  });
});
