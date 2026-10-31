import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";
import { CONFIRMED_KEY } from "@/shared/api/discrepancies";

export type Mode = "LIVE" | "SIMULATION";

/**
 * Who is signed in (multi-user design AD1 and AD11) and how they trade (AD7).
 * Cloudflare Access signs the person in before the page loads; the API verifies
 * the assertion and answers `GET /api/me`. `mode` is the user's own; `dryRunBrake`
 * is the server's emergency brake (`.env` `DRY_RUN`) over everyone, which forces
 * simulation whatever `mode` says.
 */
export interface Me {
  email: string;
  isAdmin: boolean;
  mode: Mode;
  dryRunBrake: boolean;
}

interface MeWire {
  email?: unknown;
  is_admin?: unknown;
  mode?: unknown;
  dry_run_brake?: unknown;
}

function isMode(value: unknown): value is Mode {
  return value === "LIVE" || value === "SIMULATION";
}

/**
 * Anything but a string e-mail, two booleans and a known mode is an error: a
 * malformed answer must never be readable as "this is the admin", or as "live".
 */
export async function fetchMe(): Promise<Me> {
  const body = await apiFetch<MeWire | null>("/me");
  const email = body?.email;
  const isAdmin = body?.is_admin;
  const mode = body?.mode;
  const dryRunBrake = body?.dry_run_brake;
  if (
    typeof email !== "string" ||
    typeof isAdmin !== "boolean" ||
    !isMode(mode) ||
    typeof dryRunBrake !== "boolean"
  ) {
    throw new Error("Unexpected response shape from GET /api/me");
  }
  return { email, isAdmin, mode, dryRunBrake };
}

export type ChangeModeResult =
  | { kind: "changed" }
  | { kind: "brakeOn" }
  | { kind: "needsKey" }
  | { kind: "notFlat"; symbols: string[] }
  | { kind: "unauthorized" }
  | { kind: "unknown" };

function symbolsOf(value: unknown): string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string") ? (value as string[]) : [];
}

function refusalFrom(error: ApiError): ChangeModeResult {
  if (error.status === 401) return { kind: "unauthorized" };
  if (error.status !== 409) return { kind: "unknown" };
  switch (error.code) {
    case "MODE_BRAKE_ON":
      return { kind: "brakeOn" };
    case "MODE_LIVE_NEEDS_TRADE_KEY":
      return { kind: "needsKey" };
    case "MODE_SIMULATION_NEEDS_FLAT":
      return { kind: "notFlat", symbols: symbolsOf(error.fields?.symbols) };
    default:
      return { kind: "unknown" };
  }
}

/** `POST /api/me/mode`. The route takes no user id: it changes the signed-in user and nobody else. */
export async function changeMode(mode: Mode): Promise<ChangeModeResult> {
  try {
    await apiFetch<unknown>("/me/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    return { kind: "changed" };
  } catch (error) {
    return error instanceof ApiError ? refusalFrom(error) : { kind: "unknown" };
  }
}

const ME_REFRESH_MS = 60_000;

/** Query key `['me']`, fresh for a minute: the brake can be pulled under an open page. */
export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: fetchMe,
    staleTime: ME_REFRESH_MS,
    refetchInterval: ME_REFRESH_MS,
  });
}

/**
 * The change as a mutation. On every settled attempt but a 401 it reads `me` again and waits for it before it
 * reports, whatever the answer said, so the badge behind the dialog is already the server's when the dialog
 * closes: a refusal can mean the brake was pulled a moment ago. Whether discrepancies are compared follows the
 * mode (`dry_run` of `/reconciliation/confirmed`), so that read goes again too.
 */
export function useChangeMode() {
  const queryClient = useQueryClient();
  return useMutation<ChangeModeResult, Error, Mode>({
    mutationFn: changeMode,
    onSettled: async (result) => {
      if (result?.kind === "unauthorized") return;
      await Promise.all([
        queryClient.refetchQueries({ queryKey: ["me"] }),
        queryClient.invalidateQueries({ queryKey: CONFIRMED_KEY }),
      ]);
    },
  });
}
