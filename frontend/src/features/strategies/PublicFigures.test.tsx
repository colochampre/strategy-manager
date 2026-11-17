import { fireEvent, render, screen } from "@testing-library/react";
import { Trophy } from "lucide-react";
import { describe, expect, it } from "vitest";

import { Figure } from "@/features/strategies/PublicFigures";

describe("a figure's tooltip (owner, 2026-11-17)", () => {
  it("shows on the value too, not only on the icon that heads it, and hides on leave", () => {
    render(
      <dl>
        <Figure icon={Trophy} label="Win rate" testId="figure" value="60%" />
      </dl>,
    );

    fireEvent.mouseEnter(screen.getByTestId("figure"));
    expect(screen.getByRole("tooltip")).toHaveTextContent(/^Win rate$/);
    fireEvent.mouseLeave(screen.getByTestId("figure"));
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("still shows on the icon", () => {
    render(
      <dl>
        <Figure icon={Trophy} label="Win rate" testId="figure" value="60%" />
      </dl>,
    );

    fireEvent.mouseEnter(screen.getByRole("img", { name: "Win rate" }).parentElement as HTMLElement);
    expect(screen.getByRole("tooltip")).toHaveTextContent(/^Win rate$/);
  });

  it("draws one tooltip, not two, when the pointer crosses from the icon to the value", () => {
    render(
      <dl>
        <Figure icon={Trophy} label="Win rate" testId="figure" value="60%" />
      </dl>,
    );

    fireEvent.mouseEnter(screen.getByRole("img", { name: "Win rate" }).parentElement as HTMLElement);
    fireEvent.mouseEnter(screen.getByTestId("figure"));
    expect(screen.getAllByRole("tooltip")).toHaveLength(1);
  });
});
