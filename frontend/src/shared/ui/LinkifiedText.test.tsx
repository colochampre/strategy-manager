import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LinkifiedText } from "@/shared/ui/LinkifiedText";

describe("LinkifiedText", () => {
  it("turns an http URL into a link that opens in a new tab without leaking the opener", () => {
    render(<LinkifiedText text="Docs: https://example.com/guide." />);

    const anchor = screen.getByRole("link", { name: "https://example.com/guide" });
    expect(anchor).toHaveAttribute("href", "https://example.com/guide");
    expect(anchor).toHaveAttribute("target", "_blank");
    expect(anchor).toHaveAttribute("rel", "noopener noreferrer");
    expect(anchor).toHaveClass("text-gain", "hover:text-gain-bright", "underline");
  });

  it("keeps the trailing period and the surrounding text outside the link", () => {
    const { container } = render(<LinkifiedText text="See https://example.com/x." />);

    expect(container.textContent).toBe("See https://example.com/x.");
    expect(screen.getByRole("link").textContent).toBe("https://example.com/x");
  });

  it("keeps line breaks as text", () => {
    const { container } = render(<LinkifiedText text={"one\nhttps://example.com\ntwo"} />);

    expect(container.textContent).toBe("one\nhttps://example.com\ntwo");
  });

  it("creates no element from markup and no link from another scheme", () => {
    const text = "<b>x</b> javascript:alert(1) data:text/html,x ftp://a.b/c www.example.com [m](nope)";
    const { container } = render(<LinkifiedText text={text} />);

    expect(container.textContent).toBe(text);
    expect(container.querySelector("a, b")).toBeNull();
  });
});
