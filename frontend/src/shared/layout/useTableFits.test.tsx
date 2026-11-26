import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useTableFits } from "@/shared/layout/useTableFits";

/** The table's own width; its box and the wrapper are always 500 wide. */
let tableWidth = 0;

function View() {
  const { ref, fits } = useTableFits();
  return (
    <div ref={ref}>
      {fits ? (
        <div data-testid="box">
          <table>
            <tbody>
              <tr>
                <td>cell</td>
              </tr>
            </tbody>
          </table>
        </div>
      ) : (
        <p>cards</p>
      )}
    </div>
  );
}

/** A `document.fonts` that is still loading, so the first draw is in the fallback face. */
function loadingFonts() {
  const fonts = new EventTarget() as EventTarget & { status: string; ready: Promise<unknown> };
  let settle: () => void = () => undefined;
  fonts.status = "loading";
  fonts.ready = new Promise<void>((resolve) => {
    settle = resolve;
  });
  Object.defineProperty(document, "fonts", { configurable: true, value: fonts });
  return {
    async load() {
      fonts.status = "loaded";
      settle();
      fonts.dispatchEvent(new Event("loadingdone"));
      await act(async () => {
        await fonts.ready;
      });
    },
  };
}

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockImplementation(function (this: HTMLElement) {
    return this.tagName === "TABLE" ? tableWidth : 500;
  });
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(500);
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(500);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(document, "fonts");
});

describe("useTableFits", () => {
  it("keeps the table where it fits", () => {
    tableWidth = 480;
    render(<View />);

    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("turns to the narrow form where the table spills", () => {
    tableWidth = 520;
    render(<View />);

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("cards")).toBeInTheDocument();
  });

  it("measures the table again once the fonts load: the fallback face spilled, the real one fits (RD.8)", async () => {
    const fonts = loadingFonts();
    tableWidth = 520;
    render(<View />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    tableWidth = 480;
    await fonts.load();

    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("stays in the narrow form after the fonts load when the table still spills", async () => {
    const fonts = loadingFonts();
    tableWidth = 520;
    render(<View />);

    await fonts.load();

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("cards")).toBeInTheDocument();
  });
});
