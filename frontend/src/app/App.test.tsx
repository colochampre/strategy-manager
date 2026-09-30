import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "@/app/App";
import { lock, stubApi, unlock } from "@/test/harness";

function renderApp(path: string) {
  window.history.pushState({}, "", path);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
});
afterEach(() => {
  vi.unstubAllGlobals();
  lock();
  window.history.pushState({}, "", "/");
});

describe("App", () => {
  it("hosts the router: a deep link opens its page on load, as a refresh would", async () => {
    unlock();
    renderApp("/strategies/5b0c7a52-6f43-4d6e-9c1c-0c2f3f3f2a11");

    expect(await screen.findByRole("heading", { level: 1, name: "Strategy" })).toBeInTheDocument();
  });

  it("navigates with clean paths, not hash fragments", async () => {
    unlock();
    renderApp("/");

    fireEvent.click(screen.getAllByRole("link", { name: "Settings" })[0] as HTMLElement);

    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/settings");
    expect(window.location.hash).toBe("");
  });

  it("ignores the retired #bookings hash", async () => {
    unlock();
    renderApp("/#bookings");

    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
  });

  it("test_bookings_and_tokengate_use_renamed_tokens_not_removed_ones", async () => {
    const { container } = renderApp("/");

    // Locked: the token gate renders inside the shell.
    const field = container.querySelector("input");
    expect(field).toHaveClass("border-rule", "bg-panel-2", "text-ink");
    expect(screen.getByRole("button", { name: "Unlock" })).toHaveClass("bg-gain");
    // The dry-run badge is the amber "needs your decision" role.
    expect(await screen.findByText("Dry run")).toHaveClass("text-decision");

    const removed = /(?:^|\s)(?:bg|text|border)-(?:surface-\d+|edge|ink-(?:100|300|500)|accent|profit|idle)(?:\s|$|\/)/;
    for (const el of Array.from(container.querySelectorAll("[class]"))) {
      expect(el.getAttribute("class")).not.toMatch(removed);
    }
  });
});
