import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const CSS = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "..", "index.css"), "utf8");

describe("the notification tokens of @theme (RD.0, RD.5)", () => {
  it.each([
    ["operation", "gain"],
    ["safety", "loss"],
    ["discrepancy", "decision"],
    ["notice", "ink-2"],
  ])("gives %s an edge, a soft fill over the panel and an ink, derived from %s", (kind, source) => {
    expect(CSS).toMatch(new RegExp(`--color-notif-${kind}:\\s*[^;]*var\\(--color-${source}\\)`));
    expect(CSS).toMatch(new RegExp(`--color-notif-${kind}-soft:\\s*color-mix\\([^;]*var\\(--color-panel\\)\\)`));
    expect(CSS).toMatch(new RegExp(`--color-notif-${kind}-ink:`));
  });

  it("defines the bell's shake as a theme animation that lasts 30 seconds, so 2 % of it is the 0.6 s shake", () => {
    expect(CSS).toMatch(/--animate-bell-ring:\s*bell-ring 30s /);
    expect(CSS).toMatch(/@keyframes bell-ring\s*\{/);
  });
});
