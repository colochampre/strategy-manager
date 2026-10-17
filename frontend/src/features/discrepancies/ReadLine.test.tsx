import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ReadLine, ReadState } from "@/features/discrepancies/ReadLine";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";

beforeEach(async () => {
  await act(() => i18n.changeLanguage("en"));
});
afterEach(async () => {
  await act(() => i18n.changeLanguage("en"));
});

function mount(ui: ReactNode) {
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);
}

function expectReadAgainIcon() {
  const button = screen.getByRole("button", { name: en.discrepancies.read.refresh });
  const svg = button.querySelector("svg");
  expect(svg).toHaveClass("lucide-refresh-cw", "size-4", "shrink-0");
  expect(svg).toHaveAttribute("aria-hidden", "true");
  expect(button.firstElementChild).toBe(svg);
  expect(button).toHaveClass("inline-flex", "items-center", "gap-1.5");
  expect(button).toHaveAccessibleName(en.discrepancies.read.refresh);
}

describe("the icon of Read again on the discrepancies page", () => {
  it("is drawn beside a failed first read", () => {
    mount(<ReadState status="error" errorUpdateCount={1} />);

    expectReadAgainIcon();
  });

  it("is drawn beside the last read time", () => {
    mount(<ReadLine readAt="2026-10-12T21:40:03Z" stale={false} />);

    expectReadAgainIcon();
  });
});
