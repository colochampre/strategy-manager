import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const CSS = readFileSync(join(SRC, "index.css"), "utf8");

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sources(path);
    return /\.tsx$/.test(entry.name) && !/\.test\.tsx$/.test(entry.name) ? [path] : [];
  });
}

const MODAL_FILES = sources(SRC).filter((path) => {
  const text = readFileSync(path, "utf8");
  // The mobile drawer is the shell's own motion (RD.1) and is not a dialog box.
  return /<dialog\b|role="dialog"/.test(text) && !path.endsWith("MobileDrawer.tsx");
});

describe("the motion of S13 (RD.6)", () => {
  it("defines the tip's fade-in at 150 ms and the dialog's fade-in with a scale as theme animations", () => {
    expect(CSS).toMatch(/--animate-tip-in:\s*tip-in 150ms /);
    expect(CSS).toMatch(/@keyframes tip-in\s*\{[^@]*opacity:\s*0[^@]*translateY/);
    expect(CSS).toMatch(/--animate-dialog-in:\s*dialog-in \d+ms /);
    expect(CSS).toMatch(/@keyframes dialog-in\s*\{[^@]*opacity:\s*0[^@]*scale\(/);
  });

  it("changes colour on hover and focus in 120 ms, only when the user has not asked for less motion", () => {
    const block = /@media \(prefers-reduced-motion: no-preference\)\s*\{([\s\S]*?)\n\}/.exec(CSS);
    expect(block).not.toBeNull();
    expect(block?.[1]).toMatch(/120ms/);
    expect(block?.[1]).toMatch(/transition-property:\s*color,\s*background-color,\s*border-color/);
    // It names no figure, chart or balance, and no transform: colour only.
    expect(block?.[1]).not.toMatch(/transform|opacity|width|height/);
  });

  it("finds the dialogs it is meant to cover", () => {
    expect(MODAL_FILES.length).toBeGreaterThanOrEqual(14);
  });

  it.each(MODAL_FILES.map((path) => [path.slice(SRC.length + 1), path]))("%s fades its dialog in, by motion-safe", (_name, path) => {
    const text = readFileSync(path as string, "utf8");
    expect(text).toMatch(/motion-safe:animate-dialog-in/);
  });

  it.each([["shared/ui/Tooltip.tsx"], ["shared/ui/InfoDisclosure.tsx"]])("%s fades its tip in, by motion-safe", (name) => {
    const text = readFileSync(join(SRC, name), "utf8");
    expect(text).toMatch(/motion-safe:animate-tip-in/);
  });

  it("no source applies a theme animation without motion-safe or motion-reduce", () => {
    for (const path of sources(SRC)) {
      for (const match of readFileSync(path, "utf8").matchAll(/(?<![\w:-])animate-(tip-in|dialog-in)\b/g)) {
        throw new Error(`${path} uses ${match[0]} without motion-safe`);
      }
    }
  });
});
