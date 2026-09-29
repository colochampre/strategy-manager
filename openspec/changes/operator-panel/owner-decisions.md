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

## Standing constraints

- Rule 7 applies: pools in different settlement currencies are never summed.
- i18n EN/ES.
- Tailwind palette tokens only.
- The visual design uses the frontend-design plugin and is reviewed with the owner before tasks.
- A GET-only probe (unit 1a), run by the owner on the VPS, verifies the key-permission endpoints before the validation in decision 8 is written.
