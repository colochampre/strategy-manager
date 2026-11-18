/**
 * The frame of a strategy page's settings column: Strategy settings on an own strategy, Subscribe or the reader's
 * seat on another author's. From lg up it is at least as tall as `main` leaves room for, however little it holds
 * (owner, 2026-11-17): the viewport less the top bar (`lg:h-16` and its 1 px rule) and `main`'s padding
 * (`lg:py-7`, 1.75rem above and below), both in `AppShell`. It starts at the top of `main`, so it ends at its
 * bottom; stacked under the record on a phone it keeps its own height.
 */
export const PAGE_ASIDE =
  "flex flex-col gap-4 self-start rounded-lg border border-rule bg-panel p-5 lg:min-h-[calc(100dvh-7.5rem-1px)]";
