import { fireEvent, screen } from "@testing-library/react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useHashScroll } from "@/shared/lib/useHashScroll";
import { renderAt } from "@/test/harness";

/**
 * Hash scroll (spec "Each item can be reached by its hash"): the router does nothing with a hash, so a link to
 * `#discrepancy-<id>` would seem to lead nowhere. The element the hash names is brought into view when the page
 * mounts and again whenever the hash changes while it is on screen.
 */

const scrollIntoView = vi.fn();

beforeEach(() => {
  scrollIntoView.mockClear();
  // jsdom has no layout and no scrollIntoView: the stub records the element it was called on.
  Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, writable: true, value: scrollIntoView });
});
afterEach(() => {
  Reflect.deleteProperty(Element.prototype, "scrollIntoView");
});

function Go({ to }: { to: string }) {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => void navigate(to)}>
      go {to}
    </button>
  );
}

interface PageProps {
  /** The ids on the page; the hook is told the page is ready once `ready` is true. */
  ids: string[];
  initiallyReady?: boolean;
}

function Page({ ids, initiallyReady = true }: PageProps) {
  const [ready, setReady] = useState(initiallyReady);
  useHashScroll(ready);
  return (
    <>
      <Go to="/#discrepancy-b" />
      <Go to="/#discrepancy-a" />
      <Go to="/#elsewhere" />
      <button type="button" onClick={() => setReady(true)}>
        ready
      </button>
      <button type="button" onClick={() => setReady((was) => !was)}>
        toggle
      </button>
      {ready && ids.map((id) => <p key={id} id={id} data-testid={id} />)}
    </>
  );
}

function mount(path: string, props: PageProps = { ids: ["discrepancy-a", "discrepancy-b"] }) {
  return renderAt(<Page {...props} />, path);
}

describe("useHashScroll", () => {
  it("scrolls the element the hash names into view once mounted", () => {
    mount("/#discrepancy-a");

    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView.mock.contexts[0]).toBe(screen.getByTestId("discrepancy-a"));
  });

  it.each([["/"], ["/#elsewhere"], ["/#"]])("does not scroll when mounted at %s", (path) => {
    mount(path);

    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it("does nothing, and does not throw, when the hash names no element", () => {
    mount("/#discrepancy-gone");

    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it("scrolls again when the hash changes to another element while on screen, and not when it changes to a stranger", () => {
    mount("/#discrepancy-a");
    scrollIntoView.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "go /#elsewhere" }));
    expect(scrollIntoView).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "go /#discrepancy-b" }));
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView.mock.contexts[0]).toBe(screen.getByTestId("discrepancy-b"));
  });

  it("scrolls to the first element when the hash is followed from a page that had none", () => {
    mount("/");

    fireEvent.click(screen.getByRole("button", { name: "go /#discrepancy-a" }));

    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView.mock.contexts[0]).toBe(screen.getByTestId("discrepancy-a"));
  });

  it("waits until the page is ready: an element that is not yet drawn is scrolled to once it is", () => {
    mount("/#discrepancy-a", { ids: ["discrepancy-a"], initiallyReady: false });
    expect(scrollIntoView).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "ready" }));

    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView.mock.contexts[0]).toBe(screen.getByTestId("discrepancy-a"));
  });

  it("does not scroll again when the page re-renders at the same hash", () => {
    mount("/#discrepancy-a");
    expect(scrollIntoView).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "go /#elsewhere" }));
    fireEvent.click(screen.getByRole("button", { name: "go /#discrepancy-a" }));
    expect(scrollIntoView).toHaveBeenCalledTimes(2);

    // Following a link to the hash already in the location changes nothing the hook reads, so it leaves the scroll
    // position to the owner.
    fireEvent.click(screen.getByRole("button", { name: "go /#discrepancy-a" }));
    expect(scrollIntoView).toHaveBeenCalledTimes(2);
  });

  it("reads a percent-encoded hash", () => {
    mount("/#discrepancy-a%20b", { ids: ["discrepancy-a b"] });

    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView.mock.contexts[0]).toBe(screen.getByTestId("discrepancy-a b"));
  });

  it("does not throw on a hash that is not a valid encoding", () => {
    mount("/#discrepancy-%E0%A4%A");

    expect(scrollIntoView).not.toHaveBeenCalled();
  });
});
