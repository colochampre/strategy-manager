import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/app/router";
import { TermsPage } from "@/features/terms/TermsPage";
import i18n from "@/shared/i18n";
import { LEGAL_CONTACT } from "@/shared/legal/LegalDocument";
import { lock, renderAt, stubApi, unlock } from "@/test/harness";

const SECTIONS_EN = [
  "Who provides the service",
  "What the service does",
  "Not financial advice",
  "Risks",
  "Your account and keys",
  "Strategies you publish",
  "Acceptable use",
  "Availability",
  "Liability",
  "Price",
  "Stopping",
  "Privacy",
  "Changes to these terms",
  "Governing law",
  "Contact",
];

const SECTIONS_ES = [
  "Quién presta el servicio",
  "Qué hace el servicio",
  "No es asesoramiento financiero",
  "Riesgos",
  "Su cuenta y sus keys",
  "Estrategias que publica",
  "Uso aceptable",
  "Disponibilidad",
  "Responsabilidad",
  "Precio",
  "Baja",
  "Privacidad",
  "Cambios en estos términos",
  "Ley aplicable",
  "Contacto",
];

describe("terms of service page", () => {
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
    renderAt(<TermsPage />);

    expect(screen.getByRole("heading", { level: 1, name: "Terms of service" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(SECTIONS_EN);
  });

  it("names who provides the service from the build, as the privacy policy does", () => {
    vi.stubEnv("VITE_PRIVACY_OWNER_NAME", "Jane Example");
    vi.stubEnv("VITE_PRIVACY_OWNER_ADDRESS", "1 Example Street, Example City");
    renderAt(<TermsPage />);

    const who = screen.getByText(/is provided by/);
    expect(who).toHaveTextContent("Jane Example");
    expect(who).toHaveTextContent("1 Example Street, Example City");
  });

  it("says it is not advice, that all the capital can be lost, and that funds never leave the exchange", () => {
    renderAt(<TermsPage />);

    expect(screen.getByText(/is not investment, financial, legal or tax advice/)).toBeInTheDocument();
    expect(screen.getByText(/lose all of the capital you assign/)).toBeInTheDocument();
    expect(screen.getByText(/never holds your funds/)).toBeInTheDocument();
  });

  it("links the privacy policy and names where to write", () => {
    renderAt(<TermsPage />);

    expect(screen.getByRole("link", { name: "Read the privacy policy" })).toHaveAttribute("href", "/privacy");
    expect(screen.getAllByText(new RegExp(LEGAL_CONTACT.replace(/\./g, "\\."))).length).toBeGreaterThanOrEqual(2);
  });

  it("is governed by Argentine law, and lays out like the privacy policy", () => {
    renderAt(<TermsPage />);

    expect(screen.getByText(/laws of the Argentine Republic/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveClass("text-center");
    expect(screen.getByText(/never holds your funds/).closest("article")).toHaveClass("sm:text-justify");
  });

  it("answers for the service's own damage and leaves disputes to the user's courts, as consumer law requires", () => {
    renderAt(<TermsPage />);

    expect(screen.getByText(/We answer for the damage the service itself causes you/)).toBeInTheDocument();
    expect(screen.getByText(/Market risk is yours/)).toBeInTheDocument();
    expect(screen.getByText(/the courts of your domicile/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("[JURISDICTION]");
    expect(document.body).not.toHaveTextContent("[LIABILITY LIMIT");
  });

  it("reads in Spanish", async () => {
    await i18n.changeLanguage("es");
    renderAt(<TermsPage />);

    expect(screen.getByRole("heading", { level: 1, name: "Términos y condiciones" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(SECTIONS_ES);
    expect(screen.getByText(/leyes de la República Argentina/)).toBeInTheDocument();
  });

  it("is reachable at /terms inside the shell", async () => {
    stubApi({ kind: "ok", body: { status: "ok", dry_run: true } });
    renderAt(<AppRoutes />, "/terms");

    expect(await screen.findByRole("heading", { level: 1, name: "Terms of service" })).toBeInTheDocument();
    expect(screen.getAllByRole("navigation", { name: "Sections" })).toHaveLength(2);
  });
});
