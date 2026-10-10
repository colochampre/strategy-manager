import { afterEach, describe, expect, it, vi } from "vitest";

import { copyText } from "@/shared/lib/clipboard";

/** Puts a clipboard (or none) on `navigator`, which jsdom does not provide. */
function setClipboard(clipboard: unknown): void {
  Object.defineProperty(navigator, "clipboard", { value: clipboard, configurable: true });
}

const CONSOLE_METHODS = ["log", "info", "warn", "error", "debug"] as const;

afterEach(() => {
  Reflect.deleteProperty(navigator, "clipboard");
  vi.restoreAllMocks();
});

describe("copyText", () => {
  it("writes exactly the text to navigator.clipboard.writeText and answers true", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });

    await expect(copyText("text")).resolves.toBe(true);

    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith("text");
  });

  it("writes a URL with an encoded secret untouched", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });
    const url = "https://example.org/webhook/tradingview?secret=a%2Fb%3Dc";

    await expect(copyText(url)).resolves.toBe(true);

    expect(writeText).toHaveBeenCalledWith(url);
  });

  it("answers false when navigator.clipboard is missing", async () => {
    setClipboard(undefined);

    await expect(copyText("text")).resolves.toBe(false);
  });

  it("answers false when writeText is missing", async () => {
    setClipboard({});

    await expect(copyText("text")).resolves.toBe(false);
  });

  it("answers false when the write rejects, and never throws", async () => {
    const writeText = vi.fn().mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    setClipboard({ writeText });

    await expect(copyText("text")).resolves.toBe(false);
    expect(writeText).toHaveBeenCalledWith("text");
  });

  it("answers false when writeText throws at once, and never throws", async () => {
    const writeText = vi.fn(() => {
      throw new Error("not a secure context");
    });
    setClipboard({ writeText });

    await expect(copyText("text")).resolves.toBe(false);
    expect(writeText).toHaveBeenCalledWith("text");
  });

  it.each([
    ["it works", () => setClipboard({ writeText: vi.fn().mockResolvedValue(undefined) })],
    ["the clipboard is missing", () => setClipboard(undefined)],
    ["the write rejects", () => setClipboard({ writeText: vi.fn().mockRejectedValue(new Error("secret-in-error")) })],
  ])("never logs anything, the text may be the secret: %s", async (_name, arrange) => {
    const spies = CONSOLE_METHODS.map((method) => vi.spyOn(console, method).mockImplementation(() => undefined));
    arrange();

    await copyText("the-secret");

    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
  });
});
