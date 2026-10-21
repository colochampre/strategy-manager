# Proposal: Multi-user

PROPOSE, 2026-10-21. Base `main` at `2e137f1`. Inputs: `owner-decisions.md` (R1-R7, decisions 1-12), and a read-only map of every single-user assumption in the code (summarised in `design.md`, "Where the code assumes one user").

## Intent

The system has exactly one operator. A shared bearer token authenticates the panel and gives the API no identity (`shared/infrastructure/admin_auth.py:86-99`). Keys, pools, strategies, signals, reservations and the ledger carry no owner. `DRY_RUN` is one process-wide boolean.

The owner wants other people to use the system on their own accounts, with their own keys, without handing those keys to anyone (R1, R2). A user subscribes to public strategies with a share of their own pool (R3, decision 3), sees only their own portfolio and performance (R4), chooses simulation or live for themselves (R6, decision 6), and may author strategies with their own webhook (R7). The admin keeps Discrepancies (R5) and gains a list of users (decision 8).

A second account on the same exchange is a second user (R1).

## Owner decisions (binding, not reopened)

They live in `owner-decisions.md`, numbered 1-12. In one line each:

1. A user is the e-mail Cloudflare Access verifies, by Google or one-time PIN. The app stores no password.
2. Anyone who signs in becomes a user, with no approval. Seat expiration in Cloudflare frees inactive users' seats; their data stays.
3. A subscription is a % of the subscriber's own pool, chosen by the subscriber. It joins at the strategy's next opening, never mid-position.
4. Leaving stops new openings; an open position runs until the strategy closes it.
5. An author's disable and archive work as today, for every subscriber.
6. Going live needs a confirmation and a trade-capable key. Going back to simulation is refused while the user holds real open positions or reservations.
7. `.env` `DRY_RUN` stays as an emergency brake for everyone.
8. The admin sees a list of users with their state, and no amounts.
9. A new strategy is open to subscribers at once (accepted risk). The public list shows each strategy's history.
10. An author sees the subscriber count, how many are live, and the total capital assigned per settlement currency.
11. Existing data becomes the owner's, who is the first user and the admin.
12. Monetization is left out.

## Scope

### In scope

**Identity and access**
- A `users` table. The API validates the Cloudflare Access JWT itself (signature, audience, issuer, expiry) and resolves the user by e-mail, creating them on first sign-in (decisions 1, 2).
- The admin is the e-mail named in `ADMIN_EMAIL`.
- Every endpoint is scoped to the signed-in user. Discrepancies and the users list are admin-only.
- The panel drops the bearer-token gate and learns who is signed in from `GET /api/me`.

**Ownership**
- `user_id` on keys, pools, balance snapshots, reservations, execution attempts, ledger entries and discrepancies. Strategies get an `author_id`.
- One active key per exchange **per user** (R1). A pool is identified by `(user, exchange, venue, settlement_currency)`.
- One migration backfills every existing row to the owner (decision 11). It is rehearsed on a restored copy first.

**Subscriptions and fan-out**
- A `subscriptions` table carrying the share of the pool, which moves off the strategy. A lifecycle covers joining at the next opening (decision 3) and leaving with an open position (decision 4).
- One TradingView signal is still ingested once. Processing fans it out into one **delivery** per eligible subscription, and each delivery allocates and trades on its subscriber's own pool, with that subscriber's own key.
- Today's three strategies become the owner's subscriptions, at their current `allocation_percent`.

**Authoring**
- Any user may create strategies, which are public at once (R7, decision 9).
- The webhook secret becomes **per strategy**. With one global secret, any author could post signals for another author's strategy. Existing strategies keep the current secret, so no TradingView alert has to change.

**Mode per user**
- `users.mode` is either `SIMULATION` (the default) or `LIVE`.
- A transition use case enforces decision 6.
- The effective mode is live only when `.env` `DRY_RUN=false` and the user chose live (decision 7).
- The `DRY_RUN` / `LIVE` badge becomes a control with a confirmation (R6).

**Views**
- Overview, Strategies and Settings are per user.
- There is a public strategy list carrying the history that decision 9 requires.
- The author sees aggregates (decision 10).
- The admin sees a users list (decision 8) and Discrepancies across users, labelled by user (R5).

**Worker**
- Balance sync, the degraded-key tracker, the holding guard and the reconciliation scan run per `(user, exchange)`.
- One user's broken key degrades only that user.

### Out of scope

- Monetization, fees, and the legal review they need (decision 12; operator-panel decision 4).
- More than one key per exchange per user (R1).
- Per-user notifications. Telegram stays the admin's channel.
- Private strategies (R7: every strategy is public).
- Deleting users or their data. Freeing a Cloudflare seat keeps the data (decision 2).
- An app-owned login (decision 1).
- COIN-M, Pionex execution, and a REVERSE that flips. These are unchanged from today.

### Open questions (product, asked one at a time after this proposal)

The design names three of them, each with a recommendation:

- **OQ1.** What a user in simulation trades against: a real balance read with their key, or a simulated balance for a user with no key yet.
- **OQ2.** What the `DRY_RUN=true` brake does to a real position that is already open: whether its close still runs for real (recommended), or whether everything turns simulated.
- **OQ3.** What "the strategy's return" in the public list measures, since each subscriber's return differs by share, leverage and fees.

## Impact

### DRY_RUN (rule 1)

- Rule 1 holds per user. A new user starts in `SIMULATION`.
- `.env` `DRY_RUN` defaults to true, and while it is true nobody opens a real position.
- A user's mode flips only through the transition use case: live needs a trade-capable key (decision 6), and simulation needs the user to hold nothing real.
- The startup guard that compares `DRY_RUN` with the ledger (`main.py:777-797`) becomes per user. Its exact rule depends on OQ2.

### Idempotency keys (rule 2)

- The signal's key is unchanged: `UNIQUE(strategy_id, idempotency_key)`. A duplicated webhook is still dropped at ingress.
- The fan-out is idempotent through `UNIQUE(signal_id, subscription_id)` on deliveries. A retried fan-out job creates no second delivery.
- `reservations.signal_id UNIQUE` (`allocation/infrastructure/models.py:39-41`) becomes `UNIQUE(delivery_id)`. There is still one reservation per signal per subscriber, never two.
- The ledger's `UNIQUE(exchange, venue, exchange_fill_id)` gains `user_id`. Two accounts can share a venue trade id when they trade with each other. Without the user in the key, the second account's fill would be dropped as a duplicate with no log line.

### Capital-pool isolation (rules 4 and 5)

- A pool belongs to one user, and the advisory lock is keyed by the pool, so it includes the user. One user's allocation never waits on, reads, or reserves another user's capital.
- `sum_active` is per pool, so it is per user.
- Rule 5 (Bybit's single USDT pool) holds per user.

### Credentials (rule 8)

- Unchanged in kind: envelope-encrypted, decrypted only by the worker, never returned beyond the last 4 characters.
- The withdraw-permission refusal matters more now that the system holds other people's keys. It stays.

## Rollback plan

- **The switch is the Access policy, not the code.** Every PR ships while Access admits only the owner, so production stays single-user in fact. Opening sign-up (decision 2) is the last step, done by the owner in Cloudflare. Rolling it back means restoring the owner-only policy, with no deploy.
- **Migrations.** A backup is taken before each one, and each is rehearsed on a restored copy. While only the owner's data exists, every migration has a working `downgrade`. Once other users have data, a downgrade would drop it, so from then on the path is fix-forward only, and the design says so per migration.
- **Code.** Each PR is a merge commit and can be reverted on its own while sign-up is closed. The order is in `design.md`, "Delivery".

## Risks

- **Regulation.** Running other people's money through someone else's strategies, even for free, may be a regulated activity (CNV, operator-panel decision 4). The owner accepted this risk with decision 9. This proposal is not legal advice.
- **Untrusted authors (decision 9).** A stranger can publish a strategy that others trust at once. The public list's history is the only mitigation.
- **Cross-user leaks.** Every read and write gains a user scope. One missing filter shows one user another user's money. The design requires a cross-user test for every endpoint.
- **Fan-out latency.** One signal now drives N orders. If the worker runs jobs one at a time, the last subscriber enters later and at a worse price. The design measures this before sign-up opens.
- **Venue rate limits per IP.** Every user's reads leave from the VPS's single IP. Binance counts request weight per IP.
- **Cloudflare dependency (decision 1).** Sign-in depends on Access.
