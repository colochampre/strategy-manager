import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { PageHeader } from "@/shared/ui/PageHeader";

function renderHeader(props: Partial<Parameters<typeof PageHeader>[0]> = {}) {
  return render(
    <MemoryRouter>
      <PageHeader
        crumbs={[{ label: "Strategies" }, { label: "Explore", to: "/strategies/explore" }, { label: "Momentum" }]}
        title="Momentum"
        subtitle="Public strategies."
        {...props}
      />
    </MemoryRouter>,
  );
}

describe("PageHeader", () => {
  it("draws the breadcrumb, the title and the subtitle", () => {
    renderHeader();

    expect(screen.getByRole("heading", { level: 1, name: "Momentum" })).toBeInTheDocument();
    expect(screen.getByText("Public strategies.")).toBeInTheDocument();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
    expect(within(crumbs).getByRole("link", { name: "Explore" })).toHaveAttribute("href", "/strategies/explore");
    expect(within(crumbs).getByText("Strategies").closest("a")).toBeNull();
  });

  it("marks the last crumb as the current page", () => {
    renderHeader();

    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByText("Momentum")).toHaveAttribute("aria-current", "page");
    expect(within(crumbs).getByText("Explore")).not.toHaveAttribute("aria-current");
  });

  it("draws no subtitle when there is none", () => {
    renderHeader({ subtitle: undefined });

    expect(screen.queryByText("Public strategies.")).not.toBeInTheDocument();
  });

  it("keeps the same top and bottom spacing whatever the page", () => {
    const { container } = renderHeader();

    expect(container.querySelector("header")).toHaveClass("flex", "flex-col", "mb-2");
  });
});
