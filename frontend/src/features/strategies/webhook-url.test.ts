import { describe, expect, it } from "vitest";

import { webhookUrl } from "@/features/strategies/webhook-url";

// The URL is plain concatenation of a checked origin, a constant path and the value the page already
// holds: the translated placeholder, or the percent-encoded secret (design § F).

describe("webhookUrl", () => {
  it.each([
    ["https://example.org", "<your WEBHOOK_SECRET>", "https://example.org/webhook/tradingview?secret=<your WEBHOOK_SECRET>"],
    ["http://localhost:8000", "<su WEBHOOK_SECRET>", "http://localhost:8000/webhook/tradingview?secret=<su WEBHOOK_SECRET>"],
  ])("the URL is the origin plus /webhook/tradingview?secret= plus the placeholder: %s", (origin, value, url) => {
    expect(webhookUrl(origin, value)).toBe(url);
  });

  it("carries the percent-encoded secret as it is given", () => {
    const secret = "a/b=c d+é";

    expect(webhookUrl("https://example.org", encodeURIComponent(secret))).toBe(
      "https://example.org/webhook/tradingview?secret=a%2Fb%3Dc%20d%2B%C3%A9",
    );
  });

  it.each([null, ""])("with no origin (%j) the URL is the path alone, as today", (origin) => {
    const url = webhookUrl(origin, "<your WEBHOOK_SECRET>");

    expect(url).toBe("/webhook/tradingview?secret=<your WEBHOOK_SECRET>");
    expect(url).not.toContain("null");
    expect(url).not.toContain("undefined");
  });
});
