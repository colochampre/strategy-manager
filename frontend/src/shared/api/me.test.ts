import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/shared/api/client";
import { changeMode, chooseDisplayName, fetchMe } from "@/shared/api/me";
import { jsonResponse } from "@/test/harness";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchMe", () => {
  it("reads who is signed in from /api/me", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ email: "owner@example.com", is_admin: true, mode: "LIVE", dry_run_brake: false }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchMe()).resolves.toEqual({
      email: "owner@example.com",
      isAdmin: true,
      mode: "LIVE",
      dryRunBrake: false,
      displayName: null,
    });
    expect((fetchMock.mock.calls[0] as [string])[0]).toMatch(/\/api\/me$/);
  });

  it("reads the name the user chose", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          email: "owner@example.com",
          is_admin: true,
          mode: "LIVE",
          dry_run_brake: false,
          display_name: "Ana",
        }),
      ),
    );

    await expect(fetchMe()).resolves.toMatchObject({ displayName: "Ana" });
  });

  it.each([
    ["none", null],
    ["a number", 5],
  ])("reads %s as no name: a name decides nothing, so it never refuses the answer", async (_label, name) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          email: "owner@example.com",
          is_admin: true,
          mode: "LIVE",
          dry_run_brake: false,
          display_name: name,
        }),
      ),
    );

    await expect(fetchMe()).resolves.toMatchObject({ displayName: null });
  });

  it.each([
    ["no email", { is_admin: true, mode: "LIVE", dry_run_brake: true }],
    ["a non-boolean is_admin", { email: "owner@example.com", is_admin: "yes", mode: "LIVE", dry_run_brake: true }],
    ["no mode", { email: "owner@example.com", is_admin: true, dry_run_brake: true }],
    ["a mode nobody knows", { email: "owner@example.com", is_admin: true, mode: "PAPER", dry_run_brake: true }],
    ["a non-boolean brake", { email: "owner@example.com", is_admin: true, mode: "LIVE", dry_run_brake: null }],
  ])("refuses an answer with %s, so a malformed body never reads as admin", async (_label, body) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(body)));

    await expect(fetchMe()).rejects.toThrow();
  });

  it("surfaces a refusal as an ApiError with its status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "unavailable" }, 503)));

    await expect(fetchMe()).rejects.toMatchObject({ status: 503 });
    await expect(fetchMe()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("chooseDisplayName", () => {
  function refused(error: string, status: number) {
    return jsonResponse({ detail: { error, message: "server wording" } }, status);
  }

  it("puts the name to /api/me/display-name", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);

    await expect(chooseDisplayName("Ana")).resolves.toEqual({ kind: "chosen" });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/me\/display-name$/);
    expect(init.method).toBe("PUT");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init.body))).toEqual({ display_name: "Ana" });
  });

  it.each([
    ["a taken name", refused("DISPLAY_NAME_TAKEN", 409), { kind: "taken" }],
    ["an invalid name", refused("DISPLAY_NAME_INVALID", 422), { kind: "invalid" }],
    ["a 401", jsonResponse({ detail: "unauthorized" }, 401), { kind: "unauthorized" }],
    ["a 409 of another code", refused("SOMETHING_ELSE", 409), { kind: "unknown" }],
    ["a 422 of another code", refused("SOMETHING_ELSE", 422), { kind: "unknown" }],
    ["a 500 that names a taken name", refused("DISPLAY_NAME_TAKEN", 500), { kind: "unknown" }],
    ["a 500 that names an invalid name", refused("DISPLAY_NAME_INVALID", 500), { kind: "unknown" }],
  ])("reads %s", async (_label, response, expected) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));

    await expect(chooseDisplayName("Ana")).resolves.toEqual(expected);
  });

  it("calls a failed request unknown", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));

    await expect(chooseDisplayName("Ana")).resolves.toEqual({ kind: "unknown" });
  });

  it("calls an answer it cannot read unknown", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>", { status: 200 })));

    await expect(chooseDisplayName("Ana")).resolves.toEqual({ kind: "unknown" });
  });
});

describe("changeMode", () => {
  function refusal(error: string, symbols: unknown = []) {
    return jsonResponse({ detail: { error, message: "server wording", symbols } }, 409);
  }

  it("posts the mode to /api/me/mode", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ email: "owner@example.com", is_admin: true, mode: "LIVE", dry_run_brake: false }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(changeMode("LIVE")).resolves.toEqual({ kind: "changed" });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/me\/mode$/);
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init.body))).toEqual({ mode: "LIVE" });
  });

  it.each([
    ["MODE_BRAKE_ON", { kind: "brakeOn" }],
    ["MODE_LIVE_NEEDS_TRADE_KEY", { kind: "needsKey" }],
  ])("reads the refusal %s", async (code, expected) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(refusal(code)));

    await expect(changeMode("LIVE")).resolves.toEqual(expected);
  });

  it("reads the flat refusal with its symbols", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(refusal("MODE_SIMULATION_NEEDS_FLAT", ["SFPUSDT", "STXUSDT"])));

    await expect(changeMode("SIMULATION")).resolves.toEqual({ kind: "notFlat", symbols: ["SFPUSDT", "STXUSDT"] });
  });

  it("drops a symbols field that is not a list of strings, and keeps the refusal", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(refusal("MODE_SIMULATION_NEEDS_FLAT", [1, null])));

    await expect(changeMode("SIMULATION")).resolves.toEqual({ kind: "notFlat", symbols: [] });
  });

  it("calls a 401 unauthorized", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "unauthorized" }, 401)));

    await expect(changeMode("LIVE")).resolves.toEqual({ kind: "unauthorized" });
  });

  it.each([
    ["a 409 of another code", refusal("SOMETHING_ELSE")],
    ["a 500", jsonResponse({ detail: "boom" }, 500)],
    ["a 500 that names a refusal", jsonResponse({ detail: { error: "MODE_BRAKE_ON", message: "boom" } }, 500)],
  ])("calls %s unknown", async (_name, response) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));

    await expect(changeMode("LIVE")).resolves.toEqual({ kind: "unknown" });
  });

  it("calls a failed request unknown", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));

    await expect(changeMode("LIVE")).resolves.toEqual({ kind: "unknown" });
  });
});
