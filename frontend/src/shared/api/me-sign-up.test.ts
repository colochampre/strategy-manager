import { afterEach, describe, expect, it, vi } from "vitest";

import { acceptAgain, fetchMe, giveProfile, type SignUpForm } from "@/shared/api/me";
import { jsonResponse } from "@/test/harness";

const VERSIONS = { terms: "2026-11-19-draft-1", privacy: "2026-11-19-draft-4" };
const BASE = { email: "ana@example.com", is_admin: false, mode: "SIMULATION", dry_run_brake: false, suspended: false };
const FORM: SignUpForm = {
  firstName: "Ana",
  lastName: "Pérez",
  cuit: "20-12345678-6",
  country: "AR",
  adult: true,
  truthful: true,
  accepts: true,
  versions: VERSIONS,
};

function answer(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse(body, status));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function sent(fetchMock: ReturnType<typeof vi.fn>): { url: string; method: string; body: unknown } {
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return { url, method: String(init.method), body: JSON.parse(String(init.body)) };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchMe and the sign-up step (public-site LS2, LS6)", () => {
  it("reads the profile, which step comes first and the versions in force", async () => {
    answer({
      ...BASE,
      profile: { first_name: "Ana", last_name: "Pérez", cuit: "20123456786", country: "AR" },
      profile_status: "COMPLETE",
      legal_versions: VERSIONS,
    });

    await expect(fetchMe()).resolves.toMatchObject({
      profile: { firstName: "Ana", lastName: "Pérez", cuit: "20123456786", country: "AR" },
      profileStatus: "COMPLETE",
      legalVersions: VERSIONS,
    });
  });

  it.each(["MISSING", "ACCEPTANCE_OUTDATED"])("reads %s with no profile", async (status) => {
    answer({ ...BASE, profile: null, profile_status: status, legal_versions: VERSIONS });

    await expect(fetchMe()).resolves.toMatchObject({ profile: null, profileStatus: status });
  });

  it.each([
    ["no status", { ...BASE, profile: null, legal_versions: VERSIONS }],
    ["a status nobody knows", { ...BASE, profile: null, profile_status: "DONE", legal_versions: VERSIONS }],
    ["no versions", { ...BASE, profile: null, profile_status: "MISSING" }],
    ["versions that are not text", { ...BASE, profile: null, profile_status: "MISSING", legal_versions: { terms: 1 } }],
  ])("refuses an answer with %s, so a malformed body never reads as signed up", async (_label, body) => {
    answer(body);

    await expect(fetchMe()).rejects.toThrow();
  });
});

describe("giveProfile", () => {
  it("sends the form to PUT /api/me/profile in the server's words", async () => {
    const fetchMock = answer({});

    await expect(giveProfile(FORM)).resolves.toEqual({ kind: "given" });

    expect(sent(fetchMock)).toEqual({
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
    });
  });

  it.each([
    [422, { error: "COUNTRY_NOT_SERVED", message: "m" }, { kind: "notServed" }],
    [422, { error: "PROFILE_INVALID", field: "cuit", message: "m" }, { kind: "invalid", field: "cuit" }],
    [422, { error: "DECLARATION_MISSING", field: "adult", message: "m" }, { kind: "unticked", field: "adult" }],
    [409, { error: "LEGAL_VERSION_CHANGED", message: "m" }, { kind: "versionChanged" }],
    [409, { error: "PROFILE_ALREADY_GIVEN", message: "m" }, { kind: "alreadyGiven" }],
    [401, "unauthorized", { kind: "unauthorized" }],
    [500, "boom", { kind: "unknown" }],
  ])("reads a %i %j as its refusal", async (status, detail, expected) => {
    answer({ detail }, status);

    await expect(giveProfile(FORM)).resolves.toEqual(expected);
  });

  it("reads a field it does not know as an unknown refusal, never as another field", async () => {
    answer({ detail: { error: "PROFILE_INVALID", field: "nickname", message: "m" } }, 422);

    await expect(giveProfile(FORM)).resolves.toEqual({ kind: "unknown" });
  });
});

describe("acceptAgain", () => {
  it("sends the box to POST /api/me/acceptance under the versions shown", async () => {
    const fetchMock = answer({});

    await expect(acceptAgain(VERSIONS)).resolves.toEqual({ kind: "accepted" });

    expect(sent(fetchMock)).toEqual({
      url: expect.stringMatching(/\/api\/me\/acceptance$/) as unknown as string,
      method: "POST",
      body: { accepts: true, terms_version: VERSIONS.terms, privacy_version: VERSIONS.privacy },
    });
  });

  it.each([
    [409, { error: "LEGAL_VERSION_CHANGED", message: "m" }, { kind: "versionChanged" }],
    [409, { error: "PROFILE_INCOMPLETE", profile_status: "MISSING", message: "m" }, { kind: "incomplete" }],
    [401, "unauthorized", { kind: "unauthorized" }],
    [500, "boom", { kind: "unknown" }],
  ])("reads a %i %j as its refusal", async (status, detail, expected) => {
    answer({ detail }, status);

    await expect(acceptAgain(VERSIONS)).resolves.toEqual(expected);
  });
});
