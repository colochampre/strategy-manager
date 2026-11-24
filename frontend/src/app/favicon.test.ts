// @vitest-environment node
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const html = readFileSync(join(ROOT, "index.html"), "utf8");

/** S11: the owner's favicon set, served from the root of the build (Vite copies `public/` there). */
describe("the favicon", () => {
  it.each([
    'rel="icon" href="/favicon.ico"',
    'rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png"',
    'rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png"',
    'rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png"',
    'rel="manifest" href="/site.webmanifest"',
  ])("is linked from index.html: %s", (link) => {
    const flat = html.replace(/\s+/g, " ");
    expect(flat).toContain(link);
  });

  it.each([
    "favicon.ico",
    "favicon-16x16.png",
    "favicon-32x32.png",
    "apple-touch-icon.png",
    "android-chrome-192x192.png",
    "android-chrome-512x512.png",
    "site.webmanifest",
  ])("ships %s in public/, at the root of the build", (file) => {
    expect(existsSync(join(ROOT, "public", file))).toBe(true);
  });

  it("names the app in the manifest and uses the ground colour", () => {
    const manifest = JSON.parse(readFileSync(join(ROOT, "public", "site.webmanifest"), "utf8")) as Record<string, unknown>;

    expect(manifest.name).toBe("Strategy Manager");
    expect(manifest.short_name).toBe("Strategy Manager");
    expect(manifest.theme_color).toBe("#0C1116");
    expect(manifest.background_color).toBe("#0C1116");
  });

  it("uses the same ground colour in the page's theme-color as in the palette", () => {
    const css = readFileSync(join(ROOT, "src", "index.css"), "utf8");
    expect(css).toContain("--color-ground: #0C1116");
  });
});
