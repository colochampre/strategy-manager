import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OpenReadState } from "@/features/positions/OpenReadState";
import { OPEN_POSITIONS_KEY } from "@/shared/api/positions";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";

beforeEach(async () => {
  await act(() => i18n.changeLanguage("en"));
});
afterEach(async () => {
  await act(() => i18n.changeLanguage("en"));
});

/** The component over a client whose `invalidateQueries` is watched; `show` re-renders it with other props. */
function mount(status: "pending" | "error", errorUpdateCount: number) {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries").mockResolvedValue();
  const draw = (nextStatus: "pending" | "error", nextCount: number) => (
    <QueryClientProvider client={client}>
      <OpenReadState status={nextStatus} errorUpdateCount={nextCount} />
    </QueryClientProvider>
  );
  const view = render(draw(status, errorUpdateCount));
  return { invalidate, show: (next: "pending" | "error", count: number) => view.rerender(draw(next, count)) };
}

describe("a first load that never failed", () => {
  it("draws the loading text as a status and no button", () => {
    mount("pending", 0);

    expect(screen.queryByRole("status")).toHaveTextContent(en.positions.state.loading);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("a failed read", () => {
  it("draws the alert in the loss colour and an enabled button that asks the open positions again", () => {
    const { invalidate } = mount("error", 1);

    expect(screen.queryByRole("alert")).toHaveTextContent(en.positions.state.error);
    expect(screen.getByRole("alert").className).toContain("text-loss");
    const button = screen.getByRole("button", { name: en.positions.state.refresh });
    expect(button).not.toHaveAttribute("aria-disabled");
    expect(button.className).toContain("min-h-11");

    fireEvent.click(button);

    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: OPEN_POSITIONS_KEY });
  });
});

describe("the icon of Read again", () => {
  it("draws an aria-hidden RefreshCw left of the text and leaves the accessible name as it was", () => {
    mount("error", 1);

    const button = screen.getByRole("button", { name: en.positions.state.refresh });
    const svg = button.querySelector("svg");
    expect(svg).toHaveClass("lucide-refresh-cw", "size-4", "shrink-0");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(button.firstElementChild).toBe(svg);
    expect(button).toHaveAccessibleName(en.positions.state.refresh);
    expect(button).toHaveClass("inline-flex", "items-center", "gap-1.5");
  });
});

describe("reading again after a failure", () => {
  it("keeps the same button, focused and marked aria-disabled, beside the loading text", () => {
    const { show } = mount("error", 1);
    const button = screen.getByRole("button", { name: en.positions.state.refresh });
    button.focus();

    // The query goes back to pending the moment it refetches; its error count stays above zero.
    show("pending", 1);

    expect(button).toBeInTheDocument();
    expect(document.activeElement).toBe(button);
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toBeDisabled();
    expect(screen.queryByRole("status")).toHaveTextContent(en.positions.state.loading);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("ignores a press while it reads", () => {
    const { invalidate } = mount("pending", 1);
    const button = screen.queryByRole("button", { name: en.positions.state.refresh });
    expect(button).toBeInTheDocument();

    fireEvent.click(button as HTMLElement);

    expect(invalidate).not.toHaveBeenCalled();
  });

  it("draws the alert and the enabled button again when the read fails again", () => {
    const { show } = mount("pending", 1);
    expect(screen.queryByRole("button")).toHaveAttribute("aria-disabled", "true");

    show("error", 2);

    expect(screen.queryByRole("alert")).toHaveTextContent(en.positions.state.error);
    expect(screen.getByRole("button")).not.toHaveAttribute("aria-disabled");
  });
});
