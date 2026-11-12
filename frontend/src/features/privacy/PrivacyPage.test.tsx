import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import { PRIVACY_CONTACT, PrivacyPage } from "@/features/privacy/PrivacyPage";
import i18n from "@/shared/i18n";
import { lock, renderAt, stubApi, unlock } from "@/test/harness";

const SECTIONS_EN = [
  "Who is responsible",
  "What the app stores",
  "What it is used for",
  "What other people can see",
  "Who else handles it",
  "Cookies and browser storage",
  "How long it is kept",
  "Your rights",
  "How it is protected",
  "Minimum age",
  "Changes to this policy",
  "Contact",
];

const SECTIONS_ES = [
  "Quién es responsable",
  "Qué guarda la app",
  "Para qué se usa",
  "Qué pueden ver otras personas",
  "Quién más interviene",
  "Cookies y almacenamiento del navegador",
  "Cuánto tiempo se guarda",
  "Sus derechos",
  "Cómo se protege",
  "Edad mínima",
  "Cambios en esta política",
  "Contacto",
];

describe("privacy policy page", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    unlock();
  });
  afterEach(async () => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
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

    expect(screen.getAllByText(new RegExp(PRIVACY_CONTACT.replace(/\./g, "\\."))).length).toBeGreaterThanOrEqual(3);
  });

  it("names the person responsible and their address from the build, never from the source", () => {
    vi.stubEnv("VITE_PRIVACY_OWNER_NAME", "Jane Example");
    vi.stubEnv("VITE_PRIVACY_OWNER_ADDRESS", "1 Example Street, Example City");
    renderAt(<PrivacyPage />);

    const who = screen.getByText(/is run by/);
    expect(who).toHaveTextContent("Jane Example");
    expect(who).toHaveTextContent("1 Example Street, Example City");
    expect(who).not.toHaveTextContent("[FULL NAME]");
  });

  it("shows the placeholders when the build carries no name or address", () => {
    vi.stubEnv("VITE_PRIVACY_OWNER_NAME", "");
    vi.stubEnv("VITE_PRIVACY_OWNER_ADDRESS", "");
    renderAt(<PrivacyPage />);

    const who = screen.getByText(/is run by/);
    expect(who).toHaveTextContent("[FULL NAME]");
    expect(who).toHaveTextContent("[ADDRESS]");
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

  it("centres the title and its date, and justifies the text from a tablet up", () => {
    renderAt(<PrivacyPage />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveClass("text-center");
    expect(screen.getByText(/Last updated/)).toHaveClass("text-center");
    expect(screen.getByText(/never stores a password/i).closest("article")).toHaveClass("sm:text-justify");
  });

  it("reads in Spanish", async () => {
    vi.stubEnv("VITE_PRIVACY_OWNER_NAME", "Jane Example");
    await i18n.changeLanguage("es");
    renderAt(<PrivacyPage />);

    expect(screen.getByRole("heading", { level: 1, name: "Política de privacidad" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(SECTIONS_ES);
    expect(screen.getByText(/es operado por/)).toHaveTextContent("Jane Example");
  });

  it("is reachable at /privacy inside the shell", async () => {
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
    renderAt(<AppRoutes />, "/privacy");

    expect(await screen.findByRole("heading", { level: 1, name: "Privacy policy" })).toBeInTheDocument();
    expect(screen.getAllByRole("navigation", { name: "Sections" })).toHaveLength(2);
  });
});
