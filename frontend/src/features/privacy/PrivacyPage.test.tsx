import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import { PrivacyPage } from "@/features/privacy/PrivacyPage";
import i18n from "@/shared/i18n";
import { lock, renderAt, stubApi, unlock } from "@/test/harness";

const SECTIONS_EN = [
  "Who is responsible",
  "What the app stores",
  "What it is used for",
  "What other people can see",
  "Who else handles it",
  "How long it is kept",
  "Your rights",
  "How it is protected",
  "Changes to this policy",
];

const SECTIONS_ES = [
  "Quién es responsable",
  "Qué guarda la app",
  "Para qué se usa",
  "Qué pueden ver otras personas",
  "Quién más interviene",
  "Cuánto tiempo se guarda",
  "Sus derechos",
  "Cómo se protege",
  "Cambios en esta política",
];

describe("privacy policy page", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    unlock();
  });
  afterEach(async () => {
    vi.unstubAllGlobals();
    lock();
    await i18n.changeLanguage("en");
  });

  it("titles the page and draws every section, in order", () => {
    renderAt(<PrivacyPage />);

    expect(screen.getByRole("heading", { level: 1, name: "Privacy policy" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(SECTIONS_EN);
  });

  it("names where to write, so a user can exercise their rights", () => {
    renderAt(<PrivacyPage />);

    expect(screen.getAllByText(/colochampre3@gmail\.com/).length).toBeGreaterThanOrEqual(2);
  });

  it("says what is never stored and that keys are encrypted", () => {
    renderAt(<PrivacyPage />);

    expect(screen.getByText(/never stores a password/i)).toBeInTheDocument();
    expect(screen.getByText(/encrypted before they are stored/i)).toBeInTheDocument();
  });

  it("carries the control authority's notice that Argentine law requires", () => {
    renderAt(<PrivacyPage />);

    expect(screen.getByText(/AGENCIA DE ACCESO A LA INFORMACIÓN PÚBLICA/)).toBeInTheDocument();
  });

  it("reads in Spanish", async () => {
    await i18n.changeLanguage("es");
    renderAt(<PrivacyPage />);

    expect(screen.getByRole("heading", { level: 1, name: "Política de privacidad" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(SECTIONS_ES);
  });

  it("is reachable at /privacy inside the shell", async () => {
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
    renderAt(<AppRoutes />, "/privacy");

    expect(await screen.findByRole("heading", { level: 1, name: "Privacy policy" })).toBeInTheDocument();
    expect(screen.getAllByRole("navigation", { name: "Sections" })).toHaveLength(2);
  });
});
