import { createContext, useContext } from "react";

import { isRefusal, retryTransient } from "@/shared/api/client";

/**
 * How a reader entered a strategy off the public list (decision 41): the link's token, or an invitation code. The
 * strategy's page carries them in its address (`?link=`, `?code=`) and provides them to every read and to
 * Subscribe below it; anywhere else there is none, and nothing changes.
 */
export interface Entry {
  link?: string;
  code?: string;
}

export const NO_ENTRY: Entry = {};

const EntryContext = createContext<Entry>(NO_ENTRY);

export const EntryProvider = EntryContext.Provider;

export function useEntry(): Entry {
  return useContext(EntryContext);
}

/** The query parameters of an entry, encoded; none for no entry. */
export function entryParams(entry: Entry): string[] {
  const params: string[] = [];
  if (entry.link !== undefined) params.push(`link=${encodeURIComponent(entry.link)}`);
  if (entry.code !== undefined) params.push(`code=${encodeURIComponent(entry.code)}`);
  return params;
}

function hasEntry(entry: Entry): boolean {
  return entry.link !== undefined || entry.code !== undefined;
}

interface ReadState {
  state: { error: unknown };
}

/**
 * What a read that carries an entry adds to its query. The server counts every wrong or dead code as one of the
 * reader's ten an hour, so a refused read is asked once: not retried, and not asked again on focus. Nothing for no
 * entry, so every other read keeps the client's defaults.
 */
export function entryReadOptions(entry: Entry) {
  if (!hasEntry(entry)) return {};
  return { retry: retryTransient, refetchOnWindowFocus: (query: ReadState) => !isRefusal(query.state.error) };
}

/** A poll every `ms`, stopped for good once a read that carries an entry is refused. */
export function entryPoll(entry: Entry, ms: number) {
  if (!hasEntry(entry)) return ms;
  return (query: ReadState) => (isRefusal(query.state.error) ? false : ms);
}

/** What an entry adds to a query key: nothing for no entry, so every key without one stays as it was. */
export function entryKey(entry: Entry): unknown[] {
  if (!hasEntry(entry)) return [];
  return [{ link: entry.link ?? null, code: entry.code ?? null }];
}

/** The fields of `POST /api/subscriptions` an entry adds: none for no entry. */
export function entryBody(entry: Entry): { link_token?: string; invite_code?: string } {
  return {
    ...(entry.link === undefined ? {} : { link_token: entry.link }),
    ...(entry.code === undefined ? {} : { invite_code: entry.code }),
  };
}
