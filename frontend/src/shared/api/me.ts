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
  /** The identity given at sign-up, or none yet (public-site LS3). Only its owner reads it. */
  profile: Profile | null;
  /** What the panel shows first: the panel, the whole sign-up form, or the acceptance box alone (LS2, LS6). */
  profileStatus: ProfileStatus;
  /** The terms and privacy versions in force: what the form and the box accept. */
  legalVersions: LegalVersions;
}

export type ProfileStatus = "COMPLETE" | "MISSING" | "ACCEPTANCE_OUTDATED";

export interface Profile {
  firstName: string;
  lastName: string;
  cuit: string;
  country: string;
}

export interface LegalVersions {
  terms: string;
  privacy: string;
}

interface MeWire {
  email?: unknown;
  is_admin?: unknown;
  mode?: unknown;
  dry_run_brake?: unknown;
  display_name?: unknown;
  profile?: unknown;
  profile_status?: unknown;
  legal_versions?: unknown;
}

function isMode(value: unknown): value is Mode {
  return value === "LIVE" || value === "SIMULATION";
}

function isProfileStatus(value: unknown): value is ProfileStatus {
  return value === "COMPLETE" || value === "MISSING" || value === "ACCEPTANCE_OUTDATED";
}

function legalVersionsOf(value: unknown): LegalVersions | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const { terms, privacy } = value as { terms?: unknown; privacy?: unknown };
  return typeof terms === "string" && typeof privacy === "string" ? { terms, privacy } : undefined;
}

function profileOf(value: unknown): Profile | null {
  if (typeof value !== "object" || value === null) return null;
  const { first_name, last_name, cuit, country } = value as Record<string, unknown>;
  if (
    typeof first_name !== "string" ||
    typeof last_name !== "string" ||
    typeof cuit !== "string" ||
    typeof country !== "string"
  ) {
    return null;
  }
  return { firstName: first_name, lastName: last_name, cuit, country };
}

/**
 * Anything but a string e-mail, two booleans, a known mode, a known sign-up step and the versions in force is an
 * error: a malformed answer must never be readable as "this is the admin", as "live", or as "signed up".
 */
export async function fetchMe(): Promise<Me> {
  const body = await apiFetch<MeWire | null>("/me");
  const email = body?.email;
  const isAdmin = body?.is_admin;
  const mode = body?.mode;
  const dryRunBrake = body?.dry_run_brake;
  const profileStatus = body?.profile_status;
  const legalVersions = legalVersionsOf(body?.legal_versions);
  if (
    typeof email !== "string" ||
    typeof isAdmin !== "boolean" ||
    !isMode(mode) ||
    typeof dryRunBrake !== "boolean" ||
    !isProfileStatus(profileStatus) ||
    legalVersions === undefined
  ) {
    throw new Error("Unexpected response shape from GET /api/me");
  }
  // A name decides nothing, so a missing or odd one reads as none instead of refusing the whole answer.
  const displayName = typeof body?.display_name === "string" ? body.display_name : null;
  // Nor does the profile shown back: which step to show comes from the status alone.
  const profile = profileOf(body?.profile);
  return { email, isAdmin, mode, dryRunBrake, displayName, profile, profileStatus, legalVersions };
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

export type CorrectNameResult =
  | { kind: "corrected" }
  | { kind: "invalid"; field: "first_name" | "last_name" }
  | { kind: "unauthorized" }
  | { kind: "unknown" };

/**
 * `PUT /api/me/profile/name`: the first and last name given at sign-up, corrected by their owner. The CUIT and the
 * country are not sent: the server refuses them here, and they are corrected through the contact address.
 */
export async function correctName(names: { firstName: string; lastName: string }): Promise<CorrectNameResult> {
  try {
    await apiFetch<unknown>("/me/profile/name", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ first_name: names.firstName, last_name: names.lastName }),
    });
    return { kind: "corrected" };
  } catch (error) {
    if (!(error instanceof ApiError)) return { kind: "unknown" };
    if (error.status === 401) return { kind: "unauthorized" };
    const field = error.fields?.["field"];
    if (error.code === "PROFILE_INVALID" && (field === "first_name" || field === "last_name")) {
      return { kind: "invalid", field };
    }
    return { kind: "unknown" };
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

/** The sign-up form as the panel holds it, with the versions it was shown under (public-site LS2). */
export interface SignUpForm {
  firstName: string;
  lastName: string;
  cuit: string;
  country: string;
  adult: boolean;
  truthful: boolean;
  accepts: boolean;
  versions: LegalVersions;
}

/** A field of the form the server can name in a refusal. */
export type ProfileField = "first_name" | "last_name" | "cuit";
/** A box of the form the server can name as unticked. */
export type Declaration = "adult" | "truthful" | "accepts";

export type GiveProfileResult =
  | { kind: "given" }
  | { kind: "notServed" }
  | { kind: "invalid"; field: ProfileField }
  | { kind: "unticked"; field: Declaration }
  | { kind: "versionChanged" }
  | { kind: "alreadyGiven" }
  | { kind: "unauthorized" }
  | { kind: "unknown" };

export type AcceptAgainResult =
  | { kind: "accepted" }
  | { kind: "versionChanged" }
  | { kind: "incomplete" }
  | { kind: "unauthorized" }
  | { kind: "unknown" };

const PROFILE_FIELDS: readonly string[] = ["first_name", "last_name", "cuit"];
const DECLARATIONS: readonly string[] = ["adult", "truthful", "accepts"];

function profileRefusalFrom(error: ApiError): GiveProfileResult {
  if (error.status === 401) return { kind: "unauthorized" };
  const field = error.fields?.field;
  switch (error.code) {
    case "COUNTRY_NOT_SERVED":
      return { kind: "notServed" };
    case "PROFILE_INVALID":
      return typeof field === "string" && PROFILE_FIELDS.includes(field)
        ? { kind: "invalid", field: field as ProfileField }
        : { kind: "unknown" };
    case "DECLARATION_MISSING":
      return typeof field === "string" && DECLARATIONS.includes(field)
        ? { kind: "unticked", field: field as Declaration }
        : { kind: "unknown" };
    case "LEGAL_VERSION_CHANGED":
      return { kind: "versionChanged" };
    case "PROFILE_ALREADY_GIVEN":
      return { kind: "alreadyGiven" };
    default:
      return { kind: "unknown" };
  }
}

/**
 * `PUT /api/me/profile`: the sign-up form, given once (public-site LS2). It carries the versions the form was shown
 * under, so terms that changed between loading and sending are refused instead of accepted unread.
 */
export async function giveProfile(form: SignUpForm): Promise<GiveProfileResult> {
  try {
    await apiFetch<unknown>("/me/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        first_name: form.firstName,
        last_name: form.lastName,
        cuit: form.cuit,
        country: form.country,
        adult: form.adult,
        truthful: form.truthful,
        accepts: form.accepts,
        terms_version: form.versions.terms,
        privacy_version: form.versions.privacy,
      }),
    });
    return { kind: "given" };
  } catch (error) {
    return error instanceof ApiError ? profileRefusalFrom(error) : { kind: "unknown" };
  }
}

/** `POST /api/me/acceptance`: the acceptance box alone, ticked again under new versions (LS6). */
export async function acceptAgain(versions: LegalVersions): Promise<AcceptAgainResult> {
  try {
    await apiFetch<unknown>("/me/acceptance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accepts: true, terms_version: versions.terms, privacy_version: versions.privacy }),
    });
    return { kind: "accepted" };
  } catch (error) {
    if (!(error instanceof ApiError)) return { kind: "unknown" };
    if (error.status === 401) return { kind: "unauthorized" };
    if (error.code === "LEGAL_VERSION_CHANGED") return { kind: "versionChanged" };
    if (error.code === "PROFILE_INCOMPLETE") return { kind: "incomplete" };
    return { kind: "unknown" };
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
 * True once `me` says the user has not signed up, or must accept the terms again (public-site LS2, LS6): the panel's
 * navigation and mode menu wait for it. While `me` loads or fails it is false, as the navigation was before.
 */
export function useSignUpPending(): boolean {
  const status = useMe().data?.profileStatus;
  return status !== undefined && status !== "COMPLETE";
}

/**
 * The choice as a mutation. On every settled attempt but a 401 it reads `me` again and waits for it, so the form
 * and the top bar show the name the server stored (normalized, perhaps not as typed) when the save reports.
 */
/** The correction as a mutation; like the display name, it reads `me` again and waits for it, except after a 401. */
export function useCorrectName() {
  const queryClient = useQueryClient();
  return useMutation<CorrectNameResult, Error, { firstName: string; lastName: string }>({
    mutationFn: correctName,
    onSettled: async (result) => {
      if (result?.kind === "unauthorized") return;
      await queryClient.refetchQueries({ queryKey: ["me"] });
    },
  });
}

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
 * The form and the box as mutations. On every settled attempt but a 401 they read `me` again and wait for it, so the
 * step shown next is the server's: a success opens the panel, a version change shows the new versions.
 */
export function useGiveProfile() {
  const queryClient = useQueryClient();
  return useMutation<GiveProfileResult, Error, SignUpForm>({
    mutationFn: giveProfile,
    onSettled: async (result) => {
      if (result?.kind === "unauthorized") return;
      await queryClient.refetchQueries({ queryKey: ["me"] });
    },
  });
}

export function useAcceptAgain() {
  const queryClient = useQueryClient();
  return useMutation<AcceptAgainResult, Error, LegalVersions>({
    mutationFn: acceptAgain,
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
