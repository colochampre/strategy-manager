/**
 * The frame of a strategy page's settings column: Strategy settings on an own strategy, Subscribe or the reader's
 * seat on another author's. From lg up it is at least as tall as `main` leaves room for, however little it holds
 * (owner, 2026-11-17): the viewport less everything of the shell above and below it, all in `AppShell` and
 * `ShellTopRow`. There is no top bar (RD.1); from the top of `main` down to the aside there is `main`'s top padding
 * (`lg:pt-6`, 1.5rem), the top row (`lg:min-h-13`, 3.25rem, as tall as the exchange buttons whether or not the page
 * has them) and its margin (`mb-7`, 1.75rem); under it, `main`'s bottom padding (`lg:pb-14`, 3.5rem). That is 10rem.
 * It starts at the top of the page's content, so it ends at the bottom of `main`'s viewport; stacked under the record
 * on a phone it keeps its own height.
 */
export const PAGE_ASIDE =
  "flex flex-col gap-4 self-start rounded-lg border border-rule bg-panel p-5 lg:min-h-[calc(100dvh-10rem)]";
