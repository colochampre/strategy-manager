import { fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PRIVACY_NOTICE_KEY, PRIVACY_VERSION, PrivacyNotice } from "@/features/privacy/PrivacyNotice";
import i18n from "@/shared/i18n";
import { lock, renderAt, unlock } from "@/test/harness";

describe("privacy notice", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    window.localStorage.clear();
    unlock();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    lock();
  });

  it("tells a newcomer what is stored and links the policy", () => {
    renderAt(<PrivacyNotice />);

    const notice = screen.getByRole("region", { name: "Privacy" });
    expect(notice).toHaveTextContent(/stores your e-mail/i);
    expect(screen.getByRole("link", { name: "Read the privacy policy" })).toHaveAttribute("href", "/privacy");
  });

  it("goes away once read, and remembers this version", () => {
    renderAt(<PrivacyNotice />);

    fireEvent.click(screen.getByRole("button", { name: "Got it" }));

    expect(screen.queryByRole("region", { name: "Privacy" })).not.toBeInTheDocument();
    expect(window.localStorage.getItem(PRIVACY_NOTICE_KEY)).toBe(PRIVACY_VERSION);
  });

  it("stays away for a reader who already saw this version", () => {
    window.localStorage.setItem(PRIVACY_NOTICE_KEY, PRIVACY_VERSION);
    renderAt(<PrivacyNotice />);

    expect(screen.queryByRole("region", { name: "Privacy" })).not.toBeInTheDocument();
  });

  it("closes by itself on the policy page, and counts it as read", () => {
    renderAt(<PrivacyNotice />, "/privacy");

    expect(screen.queryByRole("region", { name: "Privacy" })).not.toBeInTheDocument();
    expect(window.localStorage.getItem(PRIVACY_NOTICE_KEY)).toBe(PRIVACY_VERSION);
  });

  it("comes back when the policy changes", () => {
    window.localStorage.setItem(PRIVACY_NOTICE_KEY, "an-older-version");
    renderAt(<PrivacyNotice />);

    expect(screen.getByRole("region", { name: "Privacy" })).toBeInTheDocument();
  });

  it("still shows and closes when the browser refuses storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage refused");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage refused");
    });
    renderAt(<PrivacyNotice />);

    expect(screen.getByRole("region", { name: "Privacy" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Got it" }));
    expect(screen.queryByRole("region", { name: "Privacy" })).not.toBeInTheDocument();
  });

  it("reads in Spanish", async () => {
    await i18n.changeLanguage("es");
    renderAt(<PrivacyNotice />);

    expect(screen.getByRole("link", { name: "Leer la política de privacidad" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Entendido" })).toBeInTheDocument();
    await i18n.changeLanguage("en");
  });
});
