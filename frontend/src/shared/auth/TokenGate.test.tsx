import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { TokenGate } from "@/shared/auth/TokenGate";
import { useTokenStore } from "@/shared/auth/token-store";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";

describe("TokenGate", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useTokenStore.setState({ token: null });
  });

  it("carries the new copy in both locales, never hardcoded", () => {
    expect(en.auth?.tokenGate?.title).toBeTruthy();
    expect(en.auth?.tokenGate?.submit).toBeTruthy();
    expect(es.auth?.tokenGate?.title).toBeTruthy();
    expect(es.auth?.tokenGate?.submit).toBeTruthy();
  });

  it("renders a paste-once form instead of the children when there is no token", () => {
    render(
      <TokenGate>
        <div>protected content</div>
      </TokenGate>,
    );

    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /./ })).toBeInTheDocument();
  });

  it("uses a password input with autocomplete disabled", () => {
    render(
      <TokenGate>
        <div>protected content</div>
      </TokenGate>,
    );

    const input = screen.getByLabelText(/./) as HTMLInputElement;
    expect(input.type).toBe("password");
    expect(input.autocomplete).toBe("off");
  });

  it("renders the children once a token has been pasted and submitted", () => {
    render(
      <TokenGate>
        <div>protected content</div>
      </TokenGate>,
    );

    const input = screen.getByLabelText(/./);
    fireEvent.change(input, { target: { value: "a-real-token" } });
    fireEvent.click(screen.getByRole("button", { name: /./ }));

    expect(screen.getByText("protected content")).toBeInTheDocument();
    expect(useTokenStore.getState().token).toBe("a-real-token");
  });

  it("does not submit an empty or whitespace-only token", () => {
    render(
      <TokenGate>
        <div>protected content</div>
      </TokenGate>,
    );

    fireEvent.click(screen.getByRole("button", { name: /./ }));

    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
    expect(useTokenStore.getState().token).toBeNull();
  });

  it("renders the children directly once a token is already present", () => {
    useTokenStore.getState().setToken("existing-token");

    render(
      <TokenGate>
        <div>protected content</div>
      </TokenGate>,
    );

    expect(screen.getByText("protected content")).toBeInTheDocument();
  });
});
