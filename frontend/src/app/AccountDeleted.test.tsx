import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "@/app/App";
import { useAccountDeletedStore } from "@/shared/account/account-deleted";
import i18n from "@/shared/i18n";

afterEach(async () => {
  vi.unstubAllGlobals();
  useAccountDeletedStore.setState({ deleted: false });
  window.history.pushState({}, "", "/");
  await act(() => i18n.changeLanguage("en"));
});

function renderApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

describe("once the account is deleted (account-deletion S5)", () => {
  it("shows that it was, with a way to sign out, and nothing else", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    useAccountDeletedStore.setState({ deleted: true });
    window.history.pushState({}, "", "/settings");

    renderApp();

    expect(screen.getByRole("heading", { level: 1, name: "Your account was deleted" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Your e-mail, your name and your keys are gone. Signing in again with the same e-mail starts a new, empty account.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign out" })).toHaveAttribute("href", "/cdn-cgi/access/logout");
    expect(screen.queryByRole("navigation")).toBeNull();
    // Not even who is signed in: a read of /api/me now would make a new, empty account.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("reads in Spanish", async () => {
    vi.stubGlobal("fetch", vi.fn());
    await act(() => i18n.changeLanguage("es"));
    useAccountDeletedStore.setState({ deleted: true });

    renderApp();

    expect(screen.getByRole("heading", { level: 1, name: "Su cuenta fue eliminada" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cerrar sesión" })).toBeInTheDocument();
  });
});
