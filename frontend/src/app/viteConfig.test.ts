// @vitest-environment node
// (esbuild, pulled in by the config's plugins, refuses to load under jsdom.)
import { describe, expect, it } from "vitest";

import config from "../../vite.config";

describe("vite dev server", () => {
  it("proxies the API and /health to the backend", () => {
    const proxy = config.server?.proxy ?? {};

    expect(Object.keys(proxy)).toEqual(expect.arrayContaining(["/api", "/health"]));
  });

  it("serves index.html for client-side deep links and builds against the root path", () => {
    // `spa` makes the dev server answer /strategies/<uuid> with index.html on refresh.
    expect(config.appType).toBe("spa");
    // A non-root base would make built asset URLs relative to the deep link.
    expect(config.base ?? "/").toBe("/");
  });
});
