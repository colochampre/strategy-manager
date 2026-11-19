import { onlineManager, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAccountDeletedStore } from "@/shared/account/account-deleted";
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
  /** The name other users know them by, or none yet (decision 27). */
  displayName: string | null;
}

interface MeWire {
  email?: unknown;
  is_admin?: unknown;
  mode?: unknown;
  dry_run_brake?: unknown;
  display_name?: unknown;
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
  // A name decides nothing, so a missing or odd one reads as none instead of refusing the whole answer.
  const displayName = typeof body?.display_name === "string" ? body.display_name : null;
  return { email, isAdmin, mode, dryRunBrake, displayName };
}

export type ChooseDisplayNameResult =
  | { kind: "chosen" }
  | { kind: "taken" }
  | { kind: "invalid" }
  | { kind: "unauthorized" }
  | { kind: "unknown" };

function nameRefusalFrom(error: ApiError): ChooseDisplayNameResult {
  if (error.status === 401) return { kind: "unauthorized" };
  if (error.status === 409 && error.code === "DISPLAY_NAME_TAKEN") return { kind: "taken" };
  if (error.status === 422 && error.code === "DISPLAY_NAME_INVALID") return { kind: "invalid" };
  return { kind: "unknown" };
}

/** `PUT /api/me/display-name`. Like the mode, it names no user: it changes the signed-in one. */
export async function chooseDisplayName(name: string): Promise<ChooseDisplayNameResult> {
  try {
    await apiFetch<unknown>("/me/display-name", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name: name }),
    });
    return { kind: "chosen" };
  } catch (error) {
    return error instanceof ApiError ? nameRefusalFrom(error) : { kind: "unknown" };
  }
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

/** A strategy of the user's on which something is still held, by name. */
export interface HeldStrategy {
  name: string;
  symbols: string[];
}

export type DeleteAccountResult =
  | { kind: "deleted" }
  | { kind: "holds"; symbols: string[]; strategies: HeldStrategy[] }
  | { kind: "changed" }
  | { kind: "unauthorized" }
  | { kind: "unknown" };

/** `DELETE /api/me`. It names no user: it deletes the signed-in one's account (account-deletion S2-S5). */
export async function deleteAccount(): Promise<DeleteAccountResult> {
  try {
    await apiFetch<unknown>("/me", { method: "DELETE" });
    return { kind: "deleted" };
  } catch (error) {
    if (!(error instanceof ApiError)) return { kind: "unknown" };
    if (error.status === 401) return { kind: "unauthorized" };
    if (error.status === 409 && error.code === "ACCOUNT_HOLDS_POSITIONS") {
      return {
        kind: "holds",
        symbols: symbolsOf(error.fields?.symbols),
        strategies: heldStrategiesOf(error.fields?.strategies),
      };
    }
    if (error.status === 409 && error.code === "ACCOUNT_CHANGED") return { kind: "changed" };
    return { kind: "unknown" };
  }
}

/** Each entry with a string name; its symbols as `symbolsOf` reads them. Anything else is left out. */
function heldStrategiesOf(value: unknown): HeldStrategy[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((entry: unknown) => {
    if (typeof entry !== "object" || entry === null) return [];
    const { name, symbols } = entry as { name?: unknown; symbols?: unknown };
    return typeof name === "string" ? [{ name, symbols: symbolsOf(symbols) }] : [];
  });
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
 * The choice as a mutation. On every settled attempt but a 401 it reads `me` again and waits for it, so the form
 * and the top bar show the name the server stored (normalized, perhaps not as typed) when the save reports.
 */
export function useChooseDisplayName() {
  const queryClient = useQueryClient();
  return useMutation<ChooseDisplayNameResult, Error, string>({
    mutationFn: chooseDisplayName,
    onSettled: async (result) => {
      if (result?.kind === "unauthorized") return;
      await queryClient.refetchQueries({ queryKey: ["me"] });
    },
  });
}

/**
 * The deletion as a mutation. Any request that reaches the API once the deletion commits signs the same e-mail in
 * again as a new, empty account, and one sent while it is in flight waits for that commit (the verifier's A6). So
 * the panel goes quiet before the request goes: TanStack is told it is offline, which pauses every query, polls
 * included, instead of fetching; the ones in flight are cancelled; and only this mutation runs regardless
 * (`networkMode: "always"`). Any answer but a deletion brings the queries back. A deletion keeps them paused, drops
 * the cache and tells the app, which then unmounts every route.
 */
export function useDeleteAccount() {
  const queryClient = useQueryClient();
  const markDeleted = useAccountDeletedStore((state) => state.markDeleted);
  return useMutation<DeleteAccountResult, Error, void>({
    networkMode: "always",
    mutationFn: async () => {
      onlineManager.setOnline(false);
      let deleted = false;
      try {
        await queryClient.cancelQueries();
        const result = await deleteAccount();
        deleted = result.kind === "deleted";
        return result;
      } finally {
        if (!deleted) onlineManager.setOnline(true);
      }
    },
    onSuccess: (result) => {
      if (result.kind !== "deleted") return;
      markDeleted();
      queryClient.clear();
    },
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
