# Owner decisions for operator-panel (binding, not reopened)

Taken with the owner on 2026-09-24. Engram mirrors: `project/frontend-decisions` (1–9), `project/frontend-decisions-routing` (10), `project/frontend-decisions-archived-signals` (11), `project/frontend-decisions-curve` (12), `sdd/operator-panel/owner-decisions-proposal` (13–14).

## Decisions

1. **One strategy per pool, with an allowed-pairs list.** A signal whose symbol, normalised with `market_key`, is not on the list is refused with a WARNING. Statistics are broken down by pair. A strategy is archived, never deleted. The panel shows the webhook message ready to copy.

2. **The existing React SPA, with a shared layout shell.** The shell has a top bar for exchanges and a left sidebar (Overview, Strategies, Settings) that becomes a bottom bar on small screens. FastAPI serves the SPA on the same origin.

3. **Pending venue-close bookings go in a right-hand panel on the Overview.** Design assumes the panel is filtered by the selected exchange and drops below the dashboard on small screens.

4. **Cloudflare Access sits in front of the panel.** The panel is single-user for now, with no `user_id`. Access control stays outside the app, and the views assume no single owner.
   - Serving other users and charging them fees is a separate, large change, and may be a regulated activity (CNV).

5. **The domain is `strategymanager.trade`, on Cloudflare.**
   - The panel and the admin API run through a Cloudflare Tunnel.
   - The webhook stays on DuckDNS, and that host's proxy forwards only `/webhook/tradingview`.
   - **Revised 2026-10-09 by decision 49:** the webhook's name moves to the owner's domain. Everything else in this decision stands.

6. **The dashboard curve is the strategies' return in %, taken from realized ledger PnL.** Deposits and withdrawals do not affect it.
   - It shows the drawdown from the previous peak and a monthly grid with texture, like the pairs report.
   - It also shows the current available balance as a number, and PnL for 7D, 30D, 90D, 1Y and All.
   - There is no manual register of contributions.

7. **(Superseded by 18.) Settings manages both keys of each exchange, read-only and trade, encrypted in the vault.** `.env` no longer holds keys. A key never returns to the browser; only its last four characters and its permissions are shown.

8. **Keys are validated when saved.**
   - a. A live read with the key must succeed.
   - b. Any key with WITHDRAW permission is refused. An internal transfer permission, such as Bybit's AccountTransfer, is allowed.
   - c. The key in the read slot must not be able to trade, and the key in the trade slot must be able to trade futures.

9. **Strategy uptime is the cumulative time enabled**, taken from a log of enable and disable events. It is shown as "active X days" together with the first activation date.

10. **Clean path routes, with the admin API under `/api/...`.** The webhook (`/webhook/tradingview`) and `/health` do not move.

11. **A signal for an ARCHIVED strategy is persisted by the webhook, then refused during processing** with one WARNING that tells the owner to remove the TradingView alert.

12. **The curve is compounded** (geometric), with each trade measured against the pool capital at open. Concurrent trades are chained per day, so the same capital is not counted twice.

13. **Allowed pairs of existing strategies are seeded once by the migration**, from the distinct `market_key` symbols of the signals each strategy has already received; the owner prunes them in the panel. The form for a new strategy requires at least one pair.

14. **A strategy can be archived only when it is disabled AND has no open position.** The panel refuses otherwise and says why. So an archived strategy never holds a position, and refusing its signals (decision 11) can never strand one.

15. **The allowed-pairs list gates OPENING signals only** (design OQ1). A position already open on a pair that is later removed still closes on its signal.

16. **Day and month boundaries are UTC** (design OQ2), for the curve, the monthly grid and the PnL ranges. Trade times may be displayed in local time.

17. **The return formula in design §11 is confirmed** (design OQ3).
    - Each trade's return is `r_i = pnl_i / pool_total_at_open`.
    - Returns are summed within a UTC day and compounded across days.
    - The accepted approximation is the second-order term for trades that span days.
    - Open trades, rehearsal fills and trades without capital-at-open are excluded, and the exclusions are reported.

18. **ONE key per exchange (supersedes decision 7 and rule 8(c); design OQ4 becomes moot).**
    - Each exchange holds a single envelope-encrypted key in the vault, used for both reading and trading. `.env` holds no keys.
    - On save, the key must pass a live read (8a) and must NOT have withdraw permission (8b).
    - **A read-only key is ACCEPTED with a warning.** The panel marks that exchange "read-only", and with `DRY_RUN=false` its opening signals are refused up front with a WARNING instead of failing at the venue.
    - Why: both keys would sit in the same vault and the same worker, 8(b) already rules out withdrawal, and Bybit already works with one key. Dropping the READ/TRADE split removes the vault purpose migration, rewiring 12 call sites and a fragile deploy order.
    - Accepted cost: the trade-capable key is decrypted on every read, not only when placing orders.

19. **Visual direction A**, "the pairs report, live", with nothing mixed in from direction B.
    - Tokens, type roles and signature are in design.md's visual section.
    - Canvas: https://claude.ai/artifact/HFZmFGY5kT3ubgouYVKEgQ. Mockups: `visual/project/` (Main, Strategy, Settings, Mobile). MainB and MobileB were the alternative, and were declined.

20. **An exchange with an enabled pool but no key is DEGRADED. The worker still starts.**
    - One ERROR at startup names the exchange, and it reaches Telegram.
    - That exchange gets no balance or position reads, so allocation refuses its signals.
    - The panel marks it in amber as "no key".
    - Every other exchange keeps working, closes included.
    - This overrides the revised design's "the worker refuses to start".

21. **Saving a key enables that exchange's single futures pool automatically.**
    - The pools are Bybit linear/USDT and Binance usdt-m/USDT.
    - The exchange then appears in the top bar, and strategies can be created on it.
    - Users NEVER manage pools: there is no "activate pool" step or screen, and `min_order_size` stays system configuration.

22. **A key can be DELETED only when every strategy on that exchange is disabled AND it has no open position.** When that does not hold, the control says what is missing.
    - After deletion the pool is disabled. The exchange stays in the top bar marked "no key", so its history is still viewable.
    - Saving a key again re-enables the pool.
    - REPLACING a key is always allowed.

23. **The webhook secret is revealed only on an explicit click** ("Show secret"). This overrides the revised spec's "never rendered".
    - It is served by its own admin endpoint, called only on that click, and never included in any list or detail payload.
    - The response is `Cache-Control: no-store` and is never logged.
    - It is hidden again when the view is left.

24. **Binance keys are saved only with an explicit owner confirmation that withdrawals are disabled** (2026-09-25, after the probe).
    - The probe found `GET /sapi/v1/account/apiRestrictions` answers 403 from the VPS, so rule 8b cannot be verified server-side for Binance.
    - The Settings form requires the confirmation box ("I confirmed in Binance that this key has withdrawals disabled"). It is recorded with a timestamp, and the key is shown as "withdraw not verified".
    - Mitigation: Binance requires an IP restriction before withdrawals can be enabled, and the key is bound to the VPS.
    - Bybit stays verified server-side, fail-closed: `Wallet ⊆ {AccountTransfer, SubMemberTransfer}`. Its trade capability is `readOnly == 0`.

25. **Every processed signal records its outcome** (2026-09-28, found during PR 5).
    - Found in PR 5: `signals.status` never left `ACCEPTED`, and the job handler discarded the processing result, so a refused signal was indistinguishable from an executed one. The log line was the only record, and a WARNING does not reach Telegram.
    - A signal now ends `PROCESSED` or `REJECTED`, and a rejection stores a stable reason code and its human-readable message. The panel can then answer "what happened to this signal".
    - This covers every refusal path, old and new, not only the ones PR 5 added.
    - Signals received before this change stay `ACCEPTED`; their outcome is not reconstructed.
    - The mapping found five paths that left no log line at all: `AllocateCapital` skips, a reservation that expired before submit, a venue rejection of an order, and both settle outcomes (FILLED, NEVER_PLACED). These get their log lines first, as unit 2f in PR 5, with no schema change.
    - The outcome is final in three different jobs (`signal.process`, `execution.settle`, the open-after-close continuation), and each write shares the commit of the step that decided it. A submitted order is `PROCESSING`, not `PROCESSED`.
    - Split, agreed 2026-09-28: **PR 5b** records the outcomes decided inside `signal.process` (a migration adds the reason and decision time). **PR 5c** closes the asynchronous ones: settle, continuation abandonments, the close-to-signal link a close attempt lacks today, and jobs that exhaust their retries.

26. **The REVERSE outcome rule** (2026-09-28, PR 5b task 5b.1).
    - The close half moves the signal to `PROCESSING`; the open half decides the final status.
    - If the open is refused after the close executed, the signal is `REJECTED` with the open's reason, and the detail says the close executed.
    - A REVERSE whose close is refused ends `REJECTED` with the close's code; the open half never runs.
    - A spot REVERSE whose new side cannot be held ends `REJECTED` `REVERSE_NEW_SIDE_UNHOLDABLE`.
    - Consequence for PR 5c: a REVERSE's close fill never writes a terminal status while its open half is pending.
    - Why: the status column must tell a REVERSE that ended flat from one that flipped. The declined alternative (`PROCESSED` whenever an order executed) would show both as `PROCESSED`, and only the detail would tell them apart.
    - Design: design.md, "Addendum: signal outcomes (decision 25)", § E.

27. **A releasing signal with no position to release ends `REJECTED` `NO_POSITION_TO_CLOSE`, with a WARNING** (2026-09-29, found in PR 5b2).
    - `_handle_releases` returns early when the system holds no position for the strategy (`prior_reservation_id is None`). Today that path leaves no log line, and the signal stays `ACCEPTED` forever.
    - It happens when TradingView believes a position exists that the system never opened, for example because the open was refused for lack of capital.
    - Why `REJECTED`: the system did nothing, and TradingView and the system disagree about the position. Decision 26 already reserves `REJECTED` for "the intent was not carried out".
    - Added to PR 5b2 as task 5b.11. It is covered by decision 25's "every refusal path"; the outcome map had missed it.

28. **The worker refuses to start when `DRY_RUN` does not match the origin of an open position** (2026-09-29, found in PR 6b).
    - `DRY_RUN` is configuration read at startup, not a panel action. So the guard is a startup check beside `assert_dry_run_safe`, not a use-case refusal like archiving (decision 14).
    - With `DRY_RUN=false`, any open allocation that holds a rehearsal fill (`fake-fill-`) refuses the start.
    - With `DRY_RUN=true`, any open allocation that holds a live fill refuses the start. This is the dangerous direction: its close would go to the fake exchange, the ledger would show it flat, and the real position would stay open on the venue.
    - The refusal logs one ERROR naming every offending allocation (strategy, pool, symbol) and the way out: close those positions in the mode that opened them, then flip `DRY_RUN`.
    - "Open" uses the ledger's own rule, a net base quantity that is not zero, the same rule `derive_trade` uses.
    - Why refuse to start, when decision 20 prefers a degraded start: flipping `DRY_RUN` is a deliberate manual act done with a restart. The owner is present to read the ERROR, and a degraded worker would have to guard every signal instead.
    - Planned as PR 6d, after PR 6c.

29. **A worker that refuses its own start exits with code 78, and systemd does not restart it** (2026-09-29, found deploying PR 6d).
    - The worker unit runs `Restart=always` with `RestartSec=5` and no `StartLimit*`. Systemd's default limit (5 starts in 10 s) is never reached at a 5 s spacing, so a refused start would loop forever, one Telegram alert every few seconds. The 900 s dedupe lives in memory and dies with each process.
    - This applies to every startup refusal, not only decision 28's: the vault self-test, the lock-key check, `assert_dry_run_safe` and the mode guard.
    - Every startup refusal exits 78 (`EX_CONFIG`) after its one ERROR. The owner adds `RestartPreventExitStatus=78` to the worker unit, so a refusal alerts once and the worker stays stopped until the owner acts.
    - Anything that fails after startup keeps its current non-zero exit, and systemd keeps restarting it. That restart is the documented recovery for a dead recurring chain.
    - Rejected alternative: `StartLimitIntervalSec`/`StartLimitBurst` on the unit. It would also stop the automatic recovery from a brief database outage.
    - Planned as PR 6e, before PR 7.

30. **A Binance key's trade capability is confirmed by the owner when saving it** (2026-09-29, after probe P6).
    - Probe P6 showed that nothing reachable from the VPS reveals a Binance key's permissions.
      - A key with only "Enable Reading" reads every fapi endpoint.
      - `canTrade` and `canWithdraw` on `GET /fapi/v2/account` are account-level: both are True on a key that can neither trade futures nor withdraw.
      - SAPI `apiRestrictions` answers 403 from the VPS (decision 24).
    - So a Binance key is saved with an explicit owner confirmation that it has "Enable Futures". It sits beside decision 24's withdrawals confirmation, and both are recorded with their timestamp.
    - The key is shown as "trade not verified" as well as "withdraw not verified".
    - A wrong confirmation is caught at the venue: the first live order ends `REJECTED` `ORDER_REJECTED_BY_VENUE`, with an ERROR that reaches Telegram (PR 5b2).
    - Bybit is unchanged: `readOnly == 0` is verified server-side.
    - Rejected alternatives:
      - a second probe through `POST /fapi/v1/order/test`, whose permission behaviour is undocumented;
      - treating every Binance key as trade-capable.

31. **DELETE on an exchange without a known futures pool (Pionex) answers 404, "not served by this panel", like the PUT** (2026-09-30, PR 8b-2, unit 6e).
    - `DELETE /api/credentials/{exchange}` for an exchange with no `KNOWN_FUTURES_POOLS` entry answers 404 with FastAPI's `{"detail": ...}`, the same as `PUT` (design K5).
    - It is decided BEFORE any lock, row read or exposure query, so no advisory lock is taken and it can never become a 500.
    - It applies whether or not an active credential row exists, and it sits behind the bearer auth like every other status (401 first).
    - Its key stays active and untouched. A Pionex key is managed only through the store script.
    - Why: it touches no money-relevant state for a venue the system cannot execute on, and it mirrors K5.
    - Accepted downside: the key is listed in Settings but cannot be removed from the panel.
    - Rejected alternatives:
      - deactivating the credential only, with no pool check, which skips decision 22's flatness precondition;
      - a new refusal code for "no pool", which the design does not define.
32. **The mode badge is always visible: "Dry run", "Live", "Checking mode" or "Mode unknown"** (2026-09-30, PR 10b, unit 7-router).
    - `DryRunBadge` reads `GET /health`. `dry_run: true` shows "Dry run" in amber (`decision`); `dry_run: false` shows "Live" in `loss`.
    - While loading it shows a neutral "Checking mode"; on any failure it shows a neutral "Mode unknown". Neither state ever reads "Live".
    - Why: the design hid the badge when `dry_run` is false, but an absent badge looks the same as one still loading or one whose `/health` failed. A visible "Live" makes real-money mode unmistakable.
    - This supersedes design § Visual design, "shown only when `/health` says `dry_run`".
33. **The return chart follows the selected range, rebased to 0% at the range's start** (2026-09-30, PR 11c review).
    - Choosing 7D, 30D, 90D, 1Y or All redraws the chart for that window. `All` is the full curve, as before.
    - For a shorter range the curve is rebased: each point is `index_t / index_before_start - 1`, and the drawdown is recomputed from the peak inside the window. The chart's last point therefore equals the ledger line's return for the same range, which the server compounds from the same daily returns.
    - This ratio arithmetic runs in the browser, for display only, like the monthly grid's YEAR column. Money is still never computed client-side.
    - The time axis gets ticks that make sense for every range: day or week ticks for short ranges, month ticks for long ones.
    - Why: the owner expects the chart to show what the selector says. With a fixed chart, "30D" pressed over a year-long line reads as a bug.
    - This supersedes design § Overview, "The chart always shows All".
34. **The monthly grid shows the latest 3 years; older years sit behind "Show earlier years"** (2026-09-30, PR 11c review).
    - The three most recent UTC years are rows. Any older year is revealed in place by a toggle, never paginated.
    - The YEAR column and the monthly summary still cover the full history.
    - Why: on a desktop screen, one pool's panel must fit at first glance without vertical scroll, and an unbounded list of years grows forever.
    - Acceptance (with 35): at 1440x900 and 1920x1080, one pool's ledger line, chart, grid (3 years) and summary fit with no vertical scroll. Several pools on one exchange cannot all fit, and that is accepted.
    - **Acceptance revised by decision 36**: the viewports are 1920x915 and 1440x900, and the panel counted is the whole of it.
35. **Overview sizing: a bounded panel and a fluid decision rail** (2026-09-30, PR 11c review).
    - The pool panel has a maximum width of about 800 px, so the viewBox-sized chart stays around 330 px tall instead of growing with the screen. **Superseded by decision 36**: the panel fills the width and the chart's height is bounded directly.
    - The decision rail shrinks with the window instead of holding a fixed 22.5rem.
    - At every width from 1024 px up, the monthly grid's figures never overlap, and all five range buttons stay visible.
36. **Overview fills the width; the chart's height is bounded, not the panel's width** (2026-09-30, PR 11c second review). Supersedes decision 35's "maximum width of about 800 px" and revises decision 34's acceptance.
    - The owner saw, at 1920 wide with a viewport of about 915 px, that the 800 px panel left a large empty area on the right, that its narrow width forced line breaks that ADDED height, and that the page still scrolled on Bybit. Limiting the width was the wrong answer.
    - **Width.** The panel and its column have no maximum width. The decision rail keeps its fluid `xl:w-[clamp(15rem,25%,22.5rem)]` beside the panels from 1280 px and in-flow below it (kept: at 1920 it is 360 px, at 1440 it is about 290 px).
    - **Height.** The return chart is drawn at its MEASURED pixel width (a `ResizeObserver`, default 796 px before the first measurement and in jsdom, never below 280 px) and a FIXED height of 280 px. The `viewBox` is the pixel box, so fonts and strokes keep their size at every width, and a wider panel gets a wider chart, not a taller one.
    - **Stale note.** "Balance is out of date: last synced ..." sits on the eyebrow's row, right-aligned, instead of a line of its own. It is still plain visible text, neutral (never amber).
    - **Ledger line.** Each label and value is one pair that never breaks inside; the line wraps only between pairs, including eight-decimal BTC and ETH figures ("deepest" stays with its value).
    - **Range selector.** It lives in the chart header, top right, on the title's row; the caption sits under the title. All five 44 px buttons stay whole down to 390 px (the header wraps onto a second row instead of clipping).
    - **Revised fit criterion.** At viewports of 1920x915 and 1440x900, one pool's whole panel (eyebrow and stale note, ledger line, chart header with the selector, chart, grid title, the 3-year grid and the summary) fits with no page scroll. With "Show earlier years" expanded, overflow is acceptable. The pixel budget is an estimate from the classes (jsdom has no layout) and is in tasks.md, 8o round 2.
    - Why: the owner's real screen is wide and short. Height is what runs out, so height is what gets bounded.
37. **Interim pool order on the Overview** (2026-09-30, PR 11c second review; separate from 36 because it is a different concern and has its own follow-up, task 11f.1).
    - On an exchange with several pools, the panels are ordered: enabled pools first; then pools settled in a USD stablecoin (USDT), the larger available balance first; then every other currency by code. Pools that tie keep the server's order. Pools are ranked, never summed (rule 7).
    - Why interim: the owner wants descending USD value, so attention goes where the capital is. The system has no live price (`FixedUsdRateProvider` knows only USDT = 1), so the client cannot rank a BTC pool against an ETH or a USDT one, and no prices are invented.
    - The real request is task 11f.1: a backend USD valuation per pool (for example the venue's mark price or ticker at read time), exposed as `usd_value` on `GET /api/pools` for display and sort only, never summed. It touches only multi-pool exchanges (Pionex today, whose pools are all disabled).
38. **The page content is capped at 90rem and centred inside `main`** (2026-09-30, PR 11c third review).
    - `main` stays full width, so its scrollbar sits at the window edge. Every page lives in one inner column, `mx-auto w-full max-w-[90rem]`, which keeps `main`'s one-viewport flex contract so the token gate still fills it.
    - On a very wide screen the extra width becomes margin around the content. The pool panel and the decision rail stay side by side, and the space between them never grows.
    - Why: with decision 36 the panel filled the width, and on a wide screen the chart and the ledger line stretched further than reads well.
39. **The strategy row's sub-line shows the venue and the allowed pairs** (2026-10-02, owner review of the Strategies list).
    - The row used to show `exchange · venue · settlement currency`. The line becomes `<venue> · <pair>, <pair>`, for example `USDT-M · ETHUSDT, BTCUSDT`, with the pairs in the order the API returns them. A strategy with no pairs shows the venue alone.
    - The settlement currency still appears next to the PnL amount, so rule 7 is unaffected.
    - Why: the exchange is redundant, because the operator is already on that exchange's tab; the venue is worth keeping; the settlement currency adds nothing on that line; and the allowed pairs are what actually differs between strategies.
40. **Allowed pairs are validated against the venue's catalogue, and the dialog offers a selection among available pairs instead of free text** (2026-10-02, owner review of the Strategies list). Status: decided, NOT designed or implemented yet. **Status updated 2026-10-02:** designed, not implemented; see decision 41 and design § "Addendum: allowed pairs validated against the venue catalogue (decisions 40 and 41)".
    - Today `RegisterStrategy` and `ReplaceAllowedPairs` only normalize with `market_key()` and check the shape, so a typo (`YPF`, or `BTC` instead of `BTCUSDT`) is stored silently and the strategy then refuses every open.
    - The save must refuse a symbol the pool's venue does not list, and the free-text input is replaced by a selector over the available pairs.
    - It needs a backend catalogue read and its own PR(s); see task 9v in tasks.md. Until then the textarea stays.
41. **How decision 40 is built: a credential-free public catalogue read in the API process, refusals that fail closed, and a selector** (2026-10-02, owner choices for unit 9v).
    - **Catalogue source.** A credential-free public client in the API process reads Bybit `GET /v5/market/instruments-info?category=linear` and Binance USDⓈ-M `GET /fapi/v1/exchangeInfo`. The API process still reads no vault row and builds no signer for this (CLAUDE.md rule 8).
      - Rejected alternative: a snapshot table written by the worker.
    - **`DRY_RUN`.** The API makes these public reads to the venues even with `DRY_RUN=true`. It places no order and uses no key. No test may require the network or a credential: tests use fakes or `httpx.MockTransport`.
    - **Available pairs for a pool `(exchange, venue, settlement_currency)`.** Perpetual contracts only, in trading status, settled in the pool's settlement currency.
      - Excluded: dated futures (Bybit `BTCUSDT-25DEC26`, `LinearFutures`; Binance `BTCUSDT_251226`, `CURRENT_QUARTER`), Binance `TRADIFI_PERPETUAL`, and USDC-settled contracts.
      - The filter reads the contract type, the status and the settle or margin coin. It never decides from the symbol string alone, because `market_key` does not normalize a dated suffix.
    - **Comparison.** Always `market_key(catalogue symbol)` against the stored `market_key` form.
    - **Register.** Every submitted pair must be available, or the registration is refused.
    - **Replace.** Only the pairs being ADDED are validated. A pair already stored may be kept or removed even if the venue has since delisted it.
      - Why: decision 15 keeps a delisted pair's open position closable, and the pairs seeded by migration 0024 may be absent from the catalogue.
    - **Venue unreachable or catalogue unreadable.** The save is refused with a clear, distinct error. It fails closed: nothing is stored unvalidated.
    - **Refusal body.** A structured 422 that names the unknown symbols, `{"error": "UNKNOWN_PAIRS", "message": ..., "unknown": [...]}`, following the `STRATEGY_ARCHIVED` precedent. The dialog shows the symbols.
    - **Delivery.** After PR 12a-2: a backend delivery (port, public adapters, read endpoint, refusals) and then a frontend delivery (a searchable pair selector that replaces the textarea in `NewStrategyDialog`; `AllowedPairsEditor` of unit 9d reuses it).
      - The selector is a new component built on native elements, with no new UI dependency. It is accessible (keyboard, labels), in EN and ES, and uses Tailwind palette tokens only.
    - **A probe gate comes first.** The owner runs a GET-only script on the VPS that never places an order. It proves that both catalogue endpoints answer WITHOUT a signature and without a key from the VPS, and it records the entry counts and whether Bybit returns a `nextPageCursor`. The backend adapter tasks depend on its result.
    - Left to the design (not owner decisions): the port, the cache, the status code of the venue-unreachable refusal, the read endpoint's path, the split of each delivery into PRs. The design's open questions for the owner are in its § L.
    - **Answered 2026-10-02 (design § L, Q1): a pool with no catalogue source refuses every new strategy.** Today that is Pionex. Nothing changes in production, because every Pionex pool is disabled; a Pionex pool enabled later cannot receive a new strategy until a catalogue source exists for it. This unblocks the `PairCatalogNotServed` assertions of tasks 9vc.2 and 9vc.7.
    - The split into six sequential PRs (design § L, Q2) stands, under the session's `auto-chain` delivery. Follow-up 9vf.1 (design § L, Q3) is recorded and not yet authorized.
    - **Answered 2026-10-02 (design § L, Q3): follow-up 9vf.1 is authorized as its own small PR, right after PR 12v-1.** Probe P7 showed Bybit at 891 `linear` entries against the single 1,000-entry page the ORDER path reads, a margin of 109. Past 1,000, a valid signal on a market of the second page would be refused as not listed. The fix reuses unit 9va's cursor loop in the signed client.
42. **A strategy with no history can be deleted; one with any history can only be archived** (2026-10-02). This revises decision 1's "A strategy is archived, never deleted".
    - Why: the owner registered two strategies as a test and does not want test strategies kept in the archive.
    - **Delete is allowed only when** the strategy is disabled and has no signal, no capital reservation, no execution attempt and no ledger entry. With any of those, the delete is refused and archiving stays the only path.
    - Why the limit: reservations and ledger entries reference the strategy with a mandatory foreign key, and the ledger is append-only (rule 6). A strategy that ever acted cannot be removed without breaking that record.
    - The control lives on the strategy detail page, behind an explicit confirmation, never a single click.
    - Status: decided, NOT designed or implemented yet (task 9x). The design must list every table that references a strategy before the no-history check is written, and the spec requirement "Archive Is Terminal — Never Deleted, Never Reversed" must be revised with it. The two test strategies stay until the feature exists. **Status updated 2026-10-02:** designed, not implemented; see design § "Addendum: deleting a strategy that has no history (decision 42)". Three questions for the owner are open in its § L (enablement events, booking proposals, archived strategies); none is answered here.
    - **Answered 2026-10-02 (design addendum 9x § L, Q1): enablement events do NOT block the delete; they are deleted with the strategy.** A strategy that was switched on and off, but never received a signal and holds no reservation, execution attempt, ledger entry or booking proposal, can be deleted. What is lost is that strategy's record of when it was switched on and off; the delete's log line keeps the count, the first enable time and the uptime. This brings unit 9xf (migration 0028) into scope, with its rehearsal on a throwaway database restored from a fresh backup. Until 9xf is deployed, events still block (fail closed). Q2 (booking proposals) and Q3 (archived strategies) remain open.
    - **Answered 2026-10-02 (design addendum 9x § L, Q3): an archived strategy with no history can be deleted.** It is disabled by construction and holds nothing the archive exists to preserve; refusing it would keep every archived test strategy forever. Archiving stays terminal in the other direction: an archived strategy is never re-enabled or un-archived. This unblocks task 9xc.6 and the archived cases of 9xd.1 and 9xe.3. Q2 (booking proposals) remains open.
    - **Answered 2026-10-02 (design addendum 9x § L, Q2): a booking proposal counts as history and blocks the delete.** It records a human decision about a real operation, and its mandatory foreign key into `strategies` would refuse the delete anyway. All three questions of § L are now answered.
    - **Answered 2026-10-03 (owner, after the deploy of migration 0028): the delete dialog no longer names enablement events among the reasons of a refusal.** Since 0028 they do not block a delete, so listing them beside, for example, "3 signals" suggested something the owner had to resolve when nothing was theirs to resolve. The server's `HAS_HISTORY` body still carries `enablement_events` (the count feeds the delete's log line); only `DeleteStrategyDialog` stops rendering that kind. The six counts are still all validated before any line is trusted, so a malformed body still shows the main sentence alone, and a body whose only non-zero count is `enablement_events` shows the main sentence alone as well. Task 9d.7.
43. **Each strategy has a list of its operations that can be opened one by one, and its PnL % is measured against the pool** (2026-10-02, owner request).
    - Each closed operation shows: date and time of entry and exit, pair, LONG or SHORT, entry price, exit price, size, fees paid, PnL in the pool's settlement currency, and PnL %.
    - **PnL % is the return on the pool's capital at open**, the `return` that `GET /api/performance/strategies/{id}/trades` already serves (`pnl / pool_total_at_open`). Not the return on the position's margin (the exchange's ROE, which grows with leverage) and not the return on the notional.
    - Why: the app exists so that every strategy competes for the same pool's available capital. A 2% on the pool means the same to the account whichever strategy earned it, at whatever leverage; a return on margin would reward leverage rather than contribution.
    - An operation opened before `pool_total_at_open` was recorded has no PnL % and shows it empty, never an invented number.
    - The entry and exit prices, the size and the fees are derived from the operation's fills in the ledger and added to the trades endpoint. No migration.
    - It extends unit 9p (PR 12d), whose `TradesTable` already reads that endpoint. Its design must settle how rehearsal fills (`fake-fill-`, `DRY_RUN=true`) appear: today they are excluded from performance, so a strategy that only ran in dry run may show an empty list.
    - Status: decided, NOT designed or implemented yet.
    - **Answered 2026-10-03: rehearsal fills are listed, marked as rehearsal, and stay out of every total.** A strategy that only ran in dry run therefore shows its operations instead of an empty list. Production runs with `DRY_RUN=true`, so excluding them would show nothing until real trading starts. They never enter PnL, return, the curve, the monthly grid or the By pair figures. This unblocks the design of tasks 9p.4 and 9p.5.
    - **Answered 2026-10-03: the "Pool capital at open" column stays** in the list, although the list above does not name it: it is what explains the PnL %.
    - **Answered 2026-10-04 (design addendum "decision 43" § L, Q1): a dry-run row shows the stored numbers as they are**, beside the "Dry run" mark and a sentence that says how the row was filled. The panel shows what the ledger holds and hides nothing. The sentence must tell apart the rows filled at the fixed price of 1 (every dry-run fill written before decision 45 takes effect) from those filled at the alert's price, so an entry of 1 is never read as a real price.
    - **Answered 2026-10-04 (§ L, Q2): the detail view of an operation also shows its individual fills:** time, side, price, quantity and fee of each. They are what explains an average entry or exit price. This adds a read of one operation's fills and a table in the detail view. The margin reserved and the leverage of the opening order are not shown; that would need its own design.
    - § L, Q3 is answered as decision 45.
    - **Answered 2026-10-05 (a gap found building unit 9p.5): an operation with no base currency opens with plain headings.** An operation whose figures cannot be derived is served with a null `base_currency` and can still be opened. The two headings that carry the base currency then read without the parenthesis: "Size" / "Tamaño" in the detail dialog and "Quantity" / "Cantidad" in its fills table. No currency is guessed from the pair. The size's value already shows the dash with its reason, and the fills' quantities are stored values and are shown.
44. **The open questions of the strategy detail page, answered** (2026-10-03, owner, after reviewing PRs 12b, 12c and the tables of PR 12d by eye). They are the follow-ups of unit 12f in tasks.md and the gaps of unit 9p. None is designed or implemented yet.
    - **12f.1 Share of the pool per trade: an editable field in the settings column.** A change applies to the next allocation only and never touches one already reserved.
    - **12f.2 An archived strategy stays as built:** read-only, with the "Archived" badge, the archive control hidden and the delete control offered.
    - **12f.3 The archive confirmation stays a plain confirm button.** Archiving keeps the history; only the delete asks for the typed name.
    - **12f.4 Saving the allowed pairs gives a short "saved" text** beside the button.
    - **12f.5 Two Copy buttons: one for the webhook URL, one for the alert message.** The URL's button copies what is on screen: the placeholder while the secret is hidden, the real URL once it is revealed.
    - **12f.6 The panel shows the full webhook URL, with the host.** The host is served by the backend from a setting, never compiled into the bundle.
    - **12f.7 A revealed secret stays revealed** until the owner hides it or leaves the view. No timer and no warning text.
    - **By pair: a WIN RATE column is built**, which needs the backend to serve it. **The OPEN column of the mockup is dropped.**
      - **Answered 2026-10-06: an operation with a PnL of exactly zero is not a win.** A win is a closed operation with a PnL above zero. The win rate of a pair is its wins over its closed operations, so a zero counts in the total and not among the wins: 3 wins, 1 at zero and 1 loss read 60%. Dry-run operations stay out, as in every total. An operation with incomplete fees is counted by the PnL it has, as it already is in the pair's PnL, although near zero that sign can be wrong.
      - **Answered 2026-10-06 (design addendum "unit 12f" § N, Q4): the win rate is written with one decimal**, "58.3%", not whole as in the mockup. A whole percentage rounds 199 wins of 200 to "100%", which reads as a perfect record; one decimal writes it "99.5%". It costs no width, since the column's heading is wider than the figure.
    - **Closed trades are paged 20 rows at a time**, on a click. Nothing loads on scroll.
    - **In Spanish the side reads "LONG" and "SHORT"**, as the exchanges show it, not "Largo" and "Corto". The chart's title, "Contribution to the pool, compounded", stays.
45. **The simulated exchange fills an order at the alert's price** (2026-10-04, owner, answering design addendum "decision 43" § L, Q3).
    - Today `FakeExchangeAdapter` fills every order at a fixed price of 1 with a fee of 0, and production builds it with that default. A dry-run operation therefore reads entry 1, exit 1, fees 0, PnL 0: it says that the strategy acted, when and on which pair, and nothing about price or result.
    - From this decision on, a dry-run fill is priced at the price the alert carried, so a dry-run operation shows a simulated result.
    - Why now: the ledger is append-only, so a fill written at 1 stays at 1. Every day of dry run without this is price history that cannot be recovered, as with the USD rate at fill time (rule 7). Production runs with `DRY_RUN=true`.
    - It is its own unit, with its own design, before or beside the operations list of decision 43. It touches the `execution` module, not the performance read.
    - It does not reprice anything already in the ledger: the dry-run fills written before it stay at 1.
    - Status: decided, NOT designed or implemented yet. To settle in its design: the fee a simulated fill carries, and what fills an order whose alert carries no usable price. **Status updated 2026-10-04:** designed; see design.md § "Addendum: the simulated exchange fills at the alert's price (decision 45)". An unusable price is refused, never replaced by 1.
    - **Answered 2026-10-04 (design addendum "decision 45" § N, Q1): a simulated fill carries the venue's taker fee**, on the fill's notional, on both sides, in USDT. **Bybit: `0.00055`** (0.055%), the rate of the real round trip of 2026-08-27. **Binance: `0.0005`** (0.05%), the futures taker rate the owner reads on the account; its maker rate, 0.02%, is not used, because a simulated fill is a market order. The Binance rate is the owner's figure, not yet confirmed by a real round trip in this project. Why: a result with no fee overstates every operation, and a fee, like a price, is written once.
    - **Answered 2026-10-04 (§ N, Q2): a dry run keeps sizing a position at 1x.** The position's notional equals the capital granted, so a dry-run operation's PnL and PnL % are one leverage-th of what the same alert would produce live at the venue's leverage (3x on the real round trip). A result at 1x is exact, depends on no venue read, and can be scaled by eye. Sizing at the leverage the venue reports would be its own unit with its own design; positions already written at 1x would keep their size.
    - **Answered 2026-10-05 (follow-up 9qf.3): the panel says what an alert-priced dry-run result is.** Both texts for a row marked "alert price", the sentence under the trades table and the sentence in the detail dialog, gain one sentence, the same in both places. English: "It was sized at 1x and its fee is simulated at the taker rate, so its PnL is not what it would have made live." Spanish: "Se dimensionó a 1x y su comisión es simulada a la tasa taker, así que su PnL no es el que habría dado en real." Why: without it a dry-run PnL can be read as what the alert would have produced live, when it is one leverage-th of it and its fee is an estimate. In the dialog it goes before "It is not counted in any total." Built in unit 9p.5 (PR 12e-2); the spec and the design's i18n table carry the full texts.
46. **The operations table is made narrower** (2026-10-05, owner, after reviewing PR 12e-2 by eye with the local fixture). The table, the tags, the sentences, the detail dialog, the keyboard and the Spanish were approved. Four changes, all to the table only; the detail dialog and its fills table keep what they show. Tasks 9p.5.27 to 9p.5.30.
    - **The incomplete-fee mark no longer widens the PnL column.** It appears rarely and its words stretched every row. The cell carries an asterisk beside the PnL, and one line under the table's title says what it means, only when a row of the page on screen has it: "* A fee paid in a third currency is not in this PnL." / "* Una comisión pagada en una tercera moneda no está en este PnL." The detail dialog keeps the words.
    - **The capital column's heading reads "Pool at open" / "Pool al abrir"**, not "Pool capital at open". The detail dialog keeps the long label.
    - **Opened and Closed are compact, on two lines:** the numeric date above and the time below, as the pair and its tag are. The date follows the panel's language: `10/5/2026` in English, `5/10/2026` in Spanish. The detail dialog keeps the long format.
    - **Entry, exit and size show at most 5 decimal places**, not 8 significant digits, with no trailing zeros. **Fees show two decimals**, like the PnL beside them.
    - **A price too small for 5 decimals is not rounded to zero.** When 5 decimal places would leave fewer than 4 significant digits, 4 significant digits are shown instead (`0.00000512` stays `0.00000512`). Why: a zero in a price column reads as missing data or an error.
    - A fee charged in another currency keeps its full figure (`+ 0.00012 BNB`): two decimals would print it as zero.
    - The exact figures stay available: the detail dialog and its fills table keep full precision.
    - **Answered 2026-10-05 (the owner's second look, after the four changes above were built and approved): the table's notes sit below the table, not under its title.** The three dry-run sentences and the incomplete-fee note are information to consult when wanted, not something to read past on every visit. They go after the table and after the Previous and Next controls, so those controls do not move when a page has no note. Which notes show, and their texts, do not change. Task 9p.5.32.
47. **The webhook refuses a body larger than 64 KiB, in the application** (2026-10-06, owner, follow-up 9qf.8).
    - Found by 9qf.7: nothing bounded the size of a webhook body, and a body with an 8 MB string was stored with a 200.
    - **The limit is 65,536 bytes.** A real alert is about 300 bytes, so this leaves a margin of more than 200 times and keeps a stored row trivial.
    - **It is enforced in the application, not at the edge**, so it does not depend on how the tunnel is configured.
    - A body past the limit answers 413, stores nothing and writes one WARNING. The body is never read whole and then measured: a declared length past the limit is refused before reading, and a body with no declared length stops being read once it passes the limit.
    - Why it matters although the sender must be authenticated: the raw body is kept for good in `signals.raw_payload` and is read back by every query that selects it. Authentication happens before the body is read, so an unauthenticated request was never able to make the application read one.
48. **The share of the pool per trade is edited with a slider, as exchanges do** (2026-10-06, owner, opening the design of unit 12f; it refines decision 44's "an editable field in the settings column").
    - The mockup showed a plain number input. The owner wants the control modelled on the sliders Binance, Pionex and exchanges in general use to size an order: a track with marked stops and a handle. The reference image the owner named did not reach the session, so the design works from the pattern, not from that capture.
    - **Answered 2026-10-06, the shape of the control:**
      - The track runs from 1 to 100, in whole steps of 1. It cannot start at 0 as an exchange's does: the domain, the API and the database all require a share above zero.
      - Stops are marked at 25, 50, 75 and 100, and each can be activated to jump straight to it.
      - A number field sits beside the track, as on an exchange, to type an exact value, decimals included. The track and the field always show the same value.
      - A stored value with decimals is shown as it is. The handle rounds to a whole number only when the owner moves it.
    - **Answered 2026-10-06, how it saves: through an explicit Save button**, as the allowed pairs do, not on releasing the handle as the enable switch does. Moving the handle or activating a stop changes nothing yet: the new value shows, the button enables, and leaving the page without saving keeps the stored value. Why: the number sizes the next operation, and saving at once would let a slip of the handle or a stray touch on a stop change how much capital the strategy asks for, unconfirmed. After a save the short "saved" text of decision 44 (12f.4) appears beside the button.
    - **Answered 2026-10-06, the two short confirmation texts of unit 12f:**
      - **After a save** (the share of the pool, and the allowed pairs): "Saved" / "Guardado", beside the button. It stays until the owner changes something in that control again. No timer hides it.
      - **After a copy** (the webhook URL, and the alert message): "Copied" / "Copiado", beside the button that was activated. It stays until something else is copied or the block is closed.
      - When the browser does not allow the copy, a text says it could not be copied instead of "Copied", so the owner never believes the clipboard holds something it does not.
      - The URL's button copies what is on screen, as decision 44 (12f.5) says: the placeholder while the secret is hidden, the real URL once it is revealed.
    - **Answered 2026-10-06 (design addendum "unit 12f" § N, Q1): "Copied" beside the URL is shown only while the URL on screen is the one that was copied.** Showing or hiding the secret removes it. This narrows the rule above for the URL's button, because the two things the owner asked for met in one case: copy the URL with the placeholder, then show the secret, and "Copied" would sit beside the real URL while the clipboard still held the placeholder; pasted into TradingView, every alert would fail authentication. The alert message never changes, so its "Copied" keeps the rule above. The panel remembers only whether the secret was shown when the copy was made, never the copied text.
    - **Answered 2026-10-06 (§ N, Q2), and it adds a requirement: the share must be enough to trade the strategy's pairs.** The field accepts a share that meets the minimum needed to operate on the pairs the strategy allows. A share whose allocation would be below that minimum is not allowed. **If that cannot be resolved in this unit, it is a warning instead, and values below 1% are allowed.** The design decides which of the two it can honestly deliver and says why; it does not pick the refusal if the refusal cannot be made true.
    - **Answered 2026-10-06, after handling the prototype (`visual/project/PoolShareSlider.html`), with the Binance order form as the reference, which reached the session this time:**
      - **The field goes above the track**, as on Binance: the percentage of the pool on top, then the track.
      - **Under the track, the amount that percentage of the pool means**, in the pool's own currency, as Binance shows the amounts under its track.
      - **The stops may read as a legend rather than as buttons**; that is fine. They sit closer to the track than in the first prototype.
    - **Answered 2026-10-06, after handling the second prototype (the field above the track, the amount under it):**
      - **The explanatory paragraphs do not stay on screen.** Three paragraphs under the amount buried the control. Each explanation goes behind an information button, the usual "i" inside a circle, placed where the detail it explains is; activating the button shows the text.
      - **The number and the `%` sign sit together at the left of the field**, as on Binance, not the number at the left edge and the sign at the right.
      - **The distance of the stops' labels from the track is right** as the second prototype has it.
    - **Approved 2026-10-06: the third prototype** (`visual/project/PoolShareSlider.html`: the number and its sign together at the left of the field, two information buttons, no paragraph on screen). The owner handled it in a browser: each information button works, the percent sign follows the text, and nothing more is changed for now. That an opened explanation pushes the content below it down is accepted for now. This is the visual review the standing constraints ask for before tasks. Not covered by it: the prototype was handled in one browser, and it falls back to system fonts, not the panel's.
    - **Reviewed 2026-10-06, the same prototype, in Firefox and by keyboard.** The owner reports: in Firefox it works well and the percent sign follows the text correctly; Tab goes through the stops, and Enter, Space and Escape behave correctly. This answers, for the prototype, the two things its first approval did not cover: a second browser and the keyboard. What the owner saw in Firefox was not measured here, so it is recorded as the owner's observation, not as a statement about which mechanism Firefox applied. Still not covered, because only the real panel can show it: the panel's own fonts, the Content-Security-Policy with the built bundle served, and a screen reader.
    - **Answered 2026-10-06 (§ N, Q5): the warning on the pool's minimum order is enough for now.** No unit is recorded for a warning per pair. The design's finding stands as a known limit, and is said where the owner can read it: the exchange's minimum for each pair is not checked by the panel, the worker refuses an order that would be too small and opens nothing, and under dry run nothing refuses it.
    - **Answered 2026-10-06 (§ N, Q3): the share is shown in the settings column only.** The mockup also printed it in the page's header line ("Bybit USDT pool · 30% per trade · active 41 days…"); the header as built does not, and it stays that way.
49. **The webhook's name moves from DuckDNS to the owner's domain, and nothing else moves** (2026-10-09, owner; it revises decision 5's "the webhook stays on DuckDNS"). Tasks: unit whn in tasks.md.
    - Why: DuckDNS was chosen only because the owner had no domain then. Now there is one.
    - **What changes is the name.** A DNS-only record in the owner's zone points at the VPS, and Caddy answers for that name exactly as it answers for the DuckDNS name today. The name is `hook.strategymanager.trade`, proposed in the session and confirmed by the owner the same day.
    - **What does not change:** the webhook does not go through a tunnel, `BEHIND_CLOUDFLARE_TUNNEL` stays `false`, Caddy keeps terminating TLS and forwarding the same paths, ports 80 and 443 stay open, and the address the allowlist judges is read the same way as today. No code changes.
    - **Still true of decision 5:** the panel and the admin API go through a Cloudflare Tunnel behind Access (decision 4), and the webhook is not on the panel's origin. So the panel still has to be told the webhook's origin (`WEBHOOK_PUBLIC_ORIGIN`, unit 12f), and that setting will hold the new name.
    - **A domain does not need a tunnel.** The two were mixed up while this was discussed and the owner asked. A domain is a name; a tunnel is one way of reaching the server. The tunnel is in this project because Access can only guard traffic that passes through Cloudflare, which is a need of the panel and never of the webhook.
    - **Considered and left for later: moving the webhook into the tunnel.** It would close ports 80 and 443, retire Caddy and hide the VPS's address. It would also put Cloudflare's network and the tunnel in the path of every signal (today only the name's DNS is a third party's) and change which header the allowlist trusts. The owner may take it up later as a security improvement. What was learned for that day is kept in unit whn.
    - **`/health` stops being public** (answered 2026-10-09). Caddy forwarded it to the internet beside the webhook, and it answers `{"status": "ok", "dry_run": <bool>}`, so anyone could read whether the system trades for real. The owner recalls no service outside the VPS that reads it, so Caddy stops forwarding it in the same edit that adds the new name (task whn.2). After that the proxy forwards only the webhook, as decision 5 always said. The panel is not affected: it reads `/health` through the tunnel.
50. **A share of the pool has at most 18 decimal places** (2026-10-09, owner, answering a finding of task 12f.9.12; it replaces "with any number of decimals" in the delta spec of decision 48). Task 12f.9.17.
    - Found building the share preview: the API accepted a share with any number of decimals, and a value such as `1e-999999999` (12 characters) passes the range check. To answer, the preview writes the share out in plain notation, which for that value is a text of about 1 GB. Measured: validation accepts it, and the written length grows in a straight line (ten million decimals are 10 MB). The 1 GB case was not run. The likely effect is the API process running out of memory, and that process also receives the webhook.
    - What bounded it already: the request needs the admin token, and the panel cannot produce it (its field takes 12 characters).
    - **The limit is 18 decimal places**, the scale this system uses for every amount. A share with more is refused with the same 422 as a share outside the range, and nothing is stored.
    - **Where it applies.** The owner's yes was to "when the share is saved and in the preview". Read here as every place the API takes a share: the strategy update, the share preview, and the registration of a strategy, which saves a share too. Including registration is this session's reading, not a sentence the owner said.
    - Nothing the owner can type in the panel changes: 12 characters leave room for at most 10 decimals.

51. **From the review by eye of PR 12f-2: two layout changes, and renaming a strategy for later** (2026-10-10, owner). Tasks 12f.10.30b and 12f.10.30c; follow-up 12f.11.
    - Approved as built: the slider against the prototype, the field, the amount and its loading mark, the warning on the pool's minimum, "Saved", the keyboard, the Spanish texts, the performance and the win rate column.
    - **The list's figures line up from row to row.** On the strategies list, each row's trades, all-time PnL and all-time return sit in the same place as the row above and below. Today the width of each row's own values moves them.
    - **Save sits to the right of the text before it, in the settings column.** The column was a little too tall to be seen whole. "Save share" goes to the right of the amount line ("Asks for about ... per operation") and of what opens under it; "Save pairs" goes to the right of "Removing a pair stops new entries ...". The owner's own reading of how: the text and the button in one new row.
    - Where "Saved" goes in that row was not said. Built as: beside its button, on the button's left. This is this session's choice, shown to the owner in the next review by eye.
    - **Asked and not changed:** the owner asked that the list say "Strategies could not be loaded" where it said "The strategy could not be loaded." The list already says "Strategies could not be loaded." (`strategies.error`, EN and ES); the singular text is the detail page's (`strategies.detail.error`), where it is right. Reported back to the owner.
    - **For later, not in this PR: a strategy can be renamed from its own page**, for example from an edit icon beside the name. The API already takes `name` on the update. Not designed.
    - For this review the owner asked the assistant to edit the local fixture, `frontend/vite.fixture.config.ts`, so that its `by_pair` entries carry `wins` and `win_rate`. The file stays local and untracked; the standing rule that agents do not touch it is unchanged.

52. **"Saved" and "Copied" are the button's own text, not a text beside it** (2026-10-10, owner, from the second review by eye of PR 12f-2; it replaces "beside its button" in decision 51 and in the design of unit 12f). Task 12f.10.30d.
    - What the owner saw: "Saved" beside "Save share" pushed the explanation and the paragraphs; "Copied" beside "Copy URL" narrowed the elements of its row. The owner's words: change the text of "Copy URL" and "Copy message" to "Copied" when it is copied, and of the Save buttons to "Saved" until a change is detected, "as they were doing", so nothing is pushed only to say that it worked.
    - **When it shows does not change.** A Save button reads "Saved" exactly when "Saved" showed beside it, and a Copy button reads "Copied" exactly when "Copied" showed beside it. No timer.
    - This session's choices, to be seen by the owner in the next review by eye: the button keeps one width for both of its texts, so the change of text moves nothing; a screen reader is still told, through a status region that is not visible; a copy that FAILED is still said in a visible text beside its button, because a button that only stopped saying "Copied" would not say that nothing was copied.

## Standing constraints

- Rule 7 applies: pools in different settlement currencies are never summed.
- i18n EN/ES.
- Tailwind palette tokens only.
- The visual design uses the frontend-design plugin and is reviewed with the owner before tasks.
- A GET-only probe (unit 1a), run by the owner on the VPS, verifies the key-permission endpoints before the validation in decision 8 is written.
