import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProfileGate } from "@/features/sign-up/ProfileGate";
import i18n from "@/shared/i18n";
import en from "@/shared/i18n/locales/en.json";
import es from "@/shared/i18n/locales/es.json";
import { jsonResponse, renderAt } from "@/test/harness";

const VERSIONS = { terms: "terms-2", privacy: "privacy-5" };
const NEWER = { terms: "terms-3", privacy: "privacy-5" };
const PROFILE = { first_name: "Ana", last_name: "Pérez", cuit: "20123456786", country: "AR" };

type Status = "COMPLETE" | "MISSING" | "ACCEPTANCE_OUTDATED";

interface Server {
  status: Status;
  versions: { terms: string; privacy: string };
  /** What the next write answers: a refusal's status and detail, or nothing for a success. */
  refusal?: { status: number; detail: unknown } | undefined;
}

interface Sent {
  url: string;
  method: string;
  body: unknown;
}

/**
 * `/api/me` answers from `server`, read on every request. A write is recorded; it answers `server.refusal` once, or
 * succeeds and makes the user COMPLETE, as the API does.
 */
function serve(server: Server) {
  const sent: Sent[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.endsWith("/api/me") && method === "GET") {
      return Promise.resolve(
        jsonResponse({
          email: "ana@example.com",
          is_admin: false,
          mode: "SIMULATION",
          dry_run_brake: false,
          profile: server.status === "MISSING" ? null : PROFILE,
          profile_status: server.status,
          legal_versions: server.versions,
        }),
      );
    }
    if (url.endsWith("/api/me/profile") || url.endsWith("/api/me/acceptance")) {
      sent.push({ url, method, body: JSON.parse(String(init?.body)) });
      const refusal = server.refusal;
      if (refusal !== undefined) {
        server.refusal = undefined;
        return Promise.resolve(jsonResponse({ detail: refusal.detail }, refusal.status));
      }
      server.status = "COMPLETE";
      return Promise.resolve(jsonResponse({}));
    }
    return Promise.reject(new Error(`unexpected fetch: ${method} ${url}`));
  });
  vi.stubGlobal("fetch", fetchMock);
  return sent;
}

function renderGate(path = "/") {
  return renderAt(
    <ProfileGate>
      <div>the panel</div>
    </ProfileGate>,
    path,
  );
}

const field = (label: string) => screen.getByLabelText(label);
const box = (label: string) => screen.getByRole("checkbox", { name: label }) as HTMLInputElement;
const acceptsBox = () =>
  screen.getByRole("checkbox", { name: new RegExp(en.signUp.termsLink) }) as HTMLInputElement;
const submit = () => screen.getByRole("button", { name: en.signUp.submit }) as HTMLButtonElement;

async function fillWholeForm(cuit = "20-12345678-6") {
  await screen.findByRole("form", { name: en.signUp.label });
  fireEvent.change(field(en.signUp.firstName), { target: { value: "Ana" } });
  fireEvent.change(field(en.signUp.lastName), { target: { value: "Pérez" } });
  fireEvent.change(field(en.signUp.cuit), { target: { value: cuit } });
  fireEvent.change(field(en.signUp.country), { target: { value: "AR" } });
  fireEvent.click(box(en.signUp.adult));
  fireEvent.click(box(en.signUp.truthful));
  fireEvent.click(acceptsBox());
}

describe("ProfileGate (public-site LS2, LS6)", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("carries its copy in both locales, never hardcoded", () => {
    for (const locale of [en, es]) {
      for (const key of Object.keys(en.signUp)) {
        expect(locale.signUp[key as keyof typeof en.signUp], key).toBeTruthy();
      }
      expect(Object.keys(locale.signUp.again).sort()).toEqual(Object.keys(en.signUp.again).sort());
    }
  });

  it("shows a signed-up user the panel", async () => {
    serve({ status: "COMPLETE", versions: VERSIONS });

    renderGate();

    expect(await screen.findByText("the panel")).toBeInTheDocument();
  });

  it("shows a user with no profile the form and nothing of the panel, with no box ticked", async () => {
    serve({ status: "MISSING", versions: VERSIONS });

    renderGate();

    expect(await screen.findByRole("form", { name: en.signUp.label })).toBeInTheDocument();
    expect(screen.queryByText("the panel")).not.toBeInTheDocument();
    expect(box(en.signUp.adult).checked).toBe(false);
    expect(box(en.signUp.truthful).checked).toBe(false);
    expect(acceptsBox().checked).toBe(false);
    expect((field(en.signUp.country) as HTMLSelectElement).value).toBe("");
    expect(submit().disabled).toBe(true);
  });

  it.each(["/terms", "/privacy"])("lets a user with no profile read %s, which the form links", async (path) => {
    serve({ status: "MISSING", versions: VERSIONS });

    renderGate(path);

    expect(await screen.findByText("the panel")).toBeInTheDocument();
  });

  it("links the terms and the policy from the acceptance box, in a new tab so the form keeps what was typed", async () => {
    serve({ status: "MISSING", versions: VERSIONS });

    renderGate();
    await screen.findByRole("form", { name: en.signUp.label });

    const terms = screen.getByRole("link", { name: en.signUp.termsLink });
    const privacy = screen.getByRole("link", { name: en.signUp.privacyLink });
    expect(terms.getAttribute("href")).toBe("/terms");
    expect(privacy.getAttribute("href")).toBe("/privacy");
    expect(terms.getAttribute("target")).toBe("_blank");
    expect(privacy.getAttribute("target")).toBe("_blank");
    expect(acceptsBox().labels?.[0]?.textContent).toContain("Cloudflare, United States");
  });

  it("checks the CUIT's digit as it is typed", async () => {
    serve({ status: "MISSING", versions: VERSIONS });
    renderGate();
    await fillWholeForm("20-12345678-0");

    expect(screen.getByText(en.signUp.cuitInvalid)).toBeInTheDocument();
    expect(submit().disabled).toBe(true);

    fireEvent.change(field(en.signUp.cuit), { target: { value: "20-12345678-6" } });

    expect(screen.queryByText(en.signUp.cuitInvalid)).not.toBeInTheDocument();
    expect(submit().disabled).toBe(false);
  });

  it("says a CUIT with no possible check digit is not valid", async () => {
    serve({ status: "MISSING", versions: VERSIONS });
    renderGate();
    await fillWholeForm("2000000001");
    fireEvent.change(field(en.signUp.cuit), { target: { value: "20000000019" } });

    expect(screen.getByText(en.signUp.cuitInvalid)).toBeInTheDocument();
  });

  it("does not call a CUIT invalid while it is still being typed", async () => {
    serve({ status: "MISSING", versions: VERSIONS });
    renderGate();
    await fillWholeForm("20-1234");

    expect(screen.queryByText(en.signUp.cuitInvalid)).not.toBeInTheDocument();
    expect(submit().disabled).toBe(true);
  });

  it("tells a resident of another country the service is for Argentina only, and sends nothing", async () => {
    const sent = serve({ status: "MISSING", versions: VERSIONS });
    renderGate();
    await fillWholeForm();

    fireEvent.change(field(en.signUp.country), { target: { value: "OTHER" } });

    expect(screen.getByText(en.signUp.notServed)).toBeInTheDocument();
    expect(submit().disabled).toBe(true);
    fireEvent.submit(screen.getByRole("form", { name: en.signUp.label }));
    expect(sent).toEqual([]);
  });

  it.each([
    ["adult", () => box(en.signUp.adult)],
    ["truthful", () => box(en.signUp.truthful)],
    ["accepts", acceptsBox],
  ])("keeps the form closed while the %s box is unticked", async (_name, which) => {
    serve({ status: "MISSING", versions: VERSIONS });
    renderGate();
    await fillWholeForm();

    fireEvent.click(which());

    expect(submit().disabled).toBe(true);
  });

  it("sends the whole form under the versions it was shown, then opens the panel", async () => {
    const sent = serve({ status: "MISSING", versions: VERSIONS });
    renderGate();
    await fillWholeForm();

    fireEvent.click(submit());

    expect(await screen.findByText("the panel")).toBeInTheDocument();
    expect(sent).toEqual([
      {
        url: expect.stringMatching(/\/api\/me\/profile$/) as unknown as string,
        method: "PUT",
        body: {
          first_name: "Ana",
          last_name: "Pérez",
          cuit: "20-12345678-6",
          country: "AR",
          adult: true,
          truthful: true,
          accepts: true,
          terms_version: VERSIONS.terms,
          privacy_version: VERSIONS.privacy,
        },
      },
    ]);
  });

  it("asks the box again when the terms changed while the form was open, and sends the new versions", async () => {
    const server: Server = { status: "MISSING", versions: VERSIONS };
    const sent = serve(server);
    renderGate();
    await fillWholeForm();
    server.versions = NEWER;
    server.refusal = { status: 409, detail: { error: "LEGAL_VERSION_CHANGED", message: "m" } };

    fireEvent.click(submit());

    expect(await screen.findByText(en.signUp.versionChanged)).toBeInTheDocument();
    expect(acceptsBox().checked).toBe(false);
    expect((field(en.signUp.firstName) as HTMLInputElement).value).toBe("Ana");

    fireEvent.click(acceptsBox());
    fireEvent.click(submit());

    expect(await screen.findByText("the panel")).toBeInTheDocument();
    expect(sent.map((one) => one.body)).toEqual([
      expect.objectContaining({ terms_version: VERSIONS.terms }),
      expect.objectContaining({ terms_version: NEWER.terms }),
    ]);
  });

  it.each([
    ["cuit", en.signUp.cuitInvalid],
    ["first_name", en.signUp.nameInvalid],
  ])("shows the server's refusal of %s on the form", async (refused, message) => {
    const server: Server = { status: "MISSING", versions: VERSIONS };
    serve(server);
    renderGate();
    await fillWholeForm();
    server.refusal = { status: 422, detail: { error: "PROFILE_INVALID", field: refused, message: "m" } };

    fireEvent.click(submit());

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.queryByText("the panel")).not.toBeInTheDocument();
  });

  it("says so when the details could not be saved", async () => {
    const server: Server = { status: "MISSING", versions: VERSIONS };
    serve(server);
    renderGate();
    await fillWholeForm();
    server.refusal = { status: 500, detail: "boom" };

    fireEvent.click(submit());

    expect(await screen.findByRole("alert")).toHaveTextContent(en.signUp.failed);
  });

  it("asks a signed-up user only the box again when the versions changed (LS6)", async () => {
    const sent = serve({ status: "ACCEPTANCE_OUTDATED", versions: NEWER });
    renderGate();

    expect(await screen.findByRole("form", { name: en.signUp.again.title })).toBeInTheDocument();
    expect(screen.queryByLabelText(en.signUp.cuit)).not.toBeInTheDocument();
    expect(screen.queryByText("the panel")).not.toBeInTheDocument();
    expect(acceptsBox().checked).toBe(false);
    expect(submit().disabled).toBe(true);

    fireEvent.click(acceptsBox());
    fireEvent.click(submit());

    expect(await screen.findByText("the panel")).toBeInTheDocument();
    expect(sent).toEqual([
      {
        url: expect.stringMatching(/\/api\/me\/acceptance$/) as unknown as string,
        method: "POST",
        body: { accepts: true, terms_version: NEWER.terms, privacy_version: NEWER.privacy },
      },
    ]);
  });

  it("says so when the acceptance could not be saved", async () => {
    const server: Server = { status: "ACCEPTANCE_OUTDATED", versions: NEWER };
    serve(server);
    renderGate();
    await screen.findByRole("form", { name: en.signUp.again.title });
    server.refusal = { status: 500, detail: "boom" };

    fireEvent.click(acceptsBox());
    fireEvent.click(submit());

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(en.signUp.again.failed));
  });
});

describe("ProfileGate when the versions change under an open form (the verifier's blocker)", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  /** As `renderGate`, with the query client in hand, so a test can read `me` again as the 60-second poll does. */
  function renderWithClient() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ProfileGate>
            <div>the panel</div>
          </ProfileGate>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    return queryClient;
  }

  it("unticks the acceptance when a background read brings new versions, and never sends them under the old tick", async () => {
    const server: Server = { status: "MISSING", versions: VERSIONS };
    const sent = serve(server);
    const queryClient = renderWithClient();
    await fillWholeForm();

    server.versions = NEWER;
    await queryClient.refetchQueries({ queryKey: ["me"] });

    await waitFor(() => expect(acceptsBox().checked).toBe(false));
    expect(screen.getByText(en.signUp.versionChanged)).toBeInTheDocument();
    expect(submit().disabled).toBe(true);
    fireEvent.submit(screen.getByRole("form", { name: en.signUp.label }));
    expect(sent).toEqual([]);

    fireEvent.click(acceptsBox());
    fireEvent.click(submit());

    expect(await screen.findByText("the panel")).toBeInTheDocument();
    expect(sent.map((one) => one.body)).toEqual([expect.objectContaining({ terms_version: NEWER.terms })]);
  });

  it("unticks the box asked again when newer versions arrive before it is sent", async () => {
    const server: Server = { status: "ACCEPTANCE_OUTDATED", versions: NEWER };
    const sent = serve(server);
    const queryClient = renderWithClient();
    await screen.findByRole("form", { name: en.signUp.again.title });
    fireEvent.click(acceptsBox());

    server.versions = { terms: "terms-4", privacy: "privacy-5" };
    await queryClient.refetchQueries({ queryKey: ["me"] });

    await waitFor(() => expect(acceptsBox().checked).toBe(false));
    expect(submit().disabled).toBe(true);
    fireEvent.submit(screen.getByRole("form", { name: en.signUp.again.title }));
    expect(sent).toEqual([]);
  });
});
