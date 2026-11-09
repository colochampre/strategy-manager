# Tasks: Multi-user

Sequential PRs A-G (`design.md`, "Delivery"), each cut from `main`. Every PR ships while Cloudflare Access admits only the owner, so production stays single-user in fact until G. Strict TDD and the gate after every unit:
- backend: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`;
- frontend: `npm run lint` and `npm test`.

## Production now

- 2026-11-02: main `60e5fb3`, panel bundle `60e5fb33a2d6`, alembic `0036`, certifi `2026.10.23`.
- `DRY_RUN=false`.
- Access admits only the owner. The API verifies the Access assertion itself; `ADMIN_API_TOKEN` is gone from `.env`.
- `users` holds one row, the owner's, created by their first `/api/me`, and they have chosen their display name. Every owned row is that user's, and every strategy's `author_id` is theirs.
- Every strategy is traded through its author's subscription: 3 `ACTIVE` at 30 % and 3 `ENDED` (archived) at 5 %. Each signal has one delivery (58 of each at PR E's rehearsal). `strategies.allocation_percent` is gone (0033). The owner reads `LIVE` (0035).
- Every strategy has its own webhook secret hash, today the hash of the old global `WEBHOOK_SECRET`, so the TradingView alerts kept their URL. The 3 active strategies are `PUBLIC` and the 3 archived ones `PRIVATE`, read from the database on 2026-11-02. 0033 started them `PRIVATE`. None had been regenerated at 0034 (it refuses otherwise), so each holds that secret's last four. `GET /api/webhook-secret` no longer exists.
- The worker reports one enabled pool and one sealed key, Binance's.

## Delivery log

| PR | What | Merge | Deploy |
| --- | --- | --- | --- |
| #84 | Multi-user decisions 1-15, proposal and design; operator-panel PR 25's delivery record | `7a006fc` (parents `2e137f1`, `c4513d1`) | 2026-10-21, pull only (docs) |
| #85 | PR A: identity from Cloudflare Access, `/api/me`, the panel without the token, migration 0029 | `a1295e0` (parents `7a006fc`, `7f878ca`) | 2026-10-22, see "PR A's delivery" |
| #86 | PR B: every owned row belongs to its user, scoped reads, the per-user lock, worker and reconciliation, migration 0030 | `5632e76` (parents `a1295e0`, `814f1eb`) | 2026-10-27, see "PR B's delivery" |
| #87 | Outside this change: certifi 2026.7.22 -> 2026.10.23, which drops the distrusted `emSign ECC Root CA - G3` (eMudhra, Mozilla bug 2083449), and `tests/shared/test_tls_trust.py` to pin it | `7f67fc3` (parents `5632e76`, `39ea058`) | 2026-10-27. Pull as `strategy`; `uv sync --locked` swapped only certifi; both services restarted, both active. The venv's httpx context read `2026.10.23 113 False` (version, distinct root names, G3 present). No WARNING or ERROR in 15 minutes of both journals. No panel step. |
| #88 | PR C: subscriptions and fan-out, one delivery per eligible subscription, migrations 0031 and 0032 | `214db9b` (parents `7f67fc3`, `b2f1999`) | 2026-10-29, see "PR C's delivery" |
| #89 | PR D: a webhook secret per strategy (stored as a hash, shown once), authoring for any user scoped to them, private strategies, migration 0033 | `d75e5a4` (parents `214db9b`, `541bd16`) | 2026-10-30, see "PR D's delivery" |
| #90 | PR D2: the webhook secret masked with its last four characters, the visibility beside the settings heading, migration 0034 | `ddf8262` (parents `d75e5a4`, `e8e636c`) | 2026-10-30, see "PR D2's delivery" |
| #91 | PR E: the mode belongs to the user, the mode badge and dialog, migration 0035 | `c9b7ec0` (parents `ddf8262`, `70d5026`) | 2026-10-31, see "PR E's delivery" |
| #92 | PR E2: what must close before PR F, no migration | `44099dd` (parents `c9b7ec0`, `7ef2468`) | 2026-11-01, see "PR E2's delivery" |
| #93 | PR F: display names, the public record and list, Explore, Subscribe and Leave, the admin's users list, migration 0036 | `60e5fb3` (parents `44099dd`, `1c48808`) | 2026-11-02, see "PR F's delivery" |

## PR A: identity from Cloudflare Access

Design AD1 and AD11 (sign-in only). Every endpoint that exists today stays **admin-only** in this PR, because nothing is scoped by user until PR B. A non-admin who signs in receives 403 everywhere except `GET /api/me`.

**Risk:** item 2 (auth), item 1 (migration 0029) and item 5 (a new dependency). It needs an independent verifier before the PR.

### Backend

- [x] A.1 Dependency: PyJWT with the `crypto` extra, pinned to an exact release at least two weeks old. `cryptography` is already a dependency.
- [x] A.2 Domain `identity/domain/user.py`:
  - `User(id, email, created_at, last_seen_at)`;
  - e-mail normalisation, trimmed and lower-cased, with tests.
  - No framework imports.
- [x] A.3 Migration 0029:
  - creates `users`: `id uuid` pk; `email text` unique, with CHECK `email = lower(email)` and no whitespace; `created_at`; `last_seen_at`;
  - inserts no row: the owner's is created by their first `GET /api/me` (design, "The owner's row");
  - its `downgrade` drops the table.
  - It is rehearsed on a throwaway database restored from a fresh backup (task A.12).
- [x] A.4 Settings:
  - add `access_team_domain`, `access_aud`, `admin_email` and `dev_user_email`. `model_config` is not touched.
  - The API refuses to start:
    - with neither Access nor a dev e-mail configured;
    - with `dev_user_email` set while `DRY_RUN=false`;
    - with `admin_email` unset.
  - One test per refusal.
- [x] A.5 Application:
  - the port `IdentityVerifier`;
  - the use case `ResolveUser`, which finds or creates the user by e-mail. Two concurrent first requests create one row: `ON CONFLICT (email) DO NOTHING`, then a read. Proven on real PostgreSQL.
  - `last_seen_at` is written at most once a minute per user.
- [x] A.6 Infrastructure `AccessJwtVerifier`:
  - fetches the keys from `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs` and matches them by `kid`;
  - checks the RS256 signature, `aud`, `iss` and `exp`;
  - reads `email`.
  - The keys are cached and refreshed on an unknown `kid`, at most once a minute.
  - Tests use a locally generated RSA key and an `httpx.MockTransport` serving the keys. Each of these is refused with 401:
    - a wrong signature;
    - a wrong `aud`;
    - a wrong `iss`;
    - an expired token;
    - a token with no `email`;
    - an unknown `kid` after the refresh.
  - When the keys cannot be fetched, the answer is 503.
  - No token or claim is ever logged beyond the e-mail's domain.
- [x] A.7 FastAPI dependencies:
  - `current_user` reads `Cf-Access-Jwt-Assertion`, or the dev e-mail when configured;
  - `require_admin` builds on it and compares the e-mail with `ADMIN_EMAIL`, case-insensitively.
  - They replace `require_admin_token` on all 9 routers.
  - `strategies/infrastructure/admin_token_invariant.py` and its test are rewritten: every `/api` route depends on `require_admin`, except `/api/me`, which depends on `current_user`. `/webhook/tradingview` and `/health` are unchanged.
- [x] A.8 `GET /api/me` returns `{email, is_admin, dry_run}`. A non-admin gets 200 here and 403 on every other `/api` route, with one test per router.
- [x] A.9 Retire the bearer token (no script or doc outside `openspec`'s history called the API with it):
  - first list every caller of the HTTP API outside the panel (scripts, docs);
  - then remove `admin_api_token`, `AdminTokenAuth` and `require_admin_token`.
  - The owner removes `ADMIN_API_TOKEN` from the VPS `.env` after the deploy (A.13). A leftover line is ignored, as with the old key settings.
- [x] A.10 Tests: one `current_user` override fixture replaces the token header across the existing suites. Each suite keeps one unauthenticated test asserting 401.

### Frontend

- [x] A.11 The panel without a token:
  - remove `TokenGate`, `token-store` and the `Authorization` header from `shared/api/client.ts`;
  - a 401 reloads the page, so that Access signs the user in again;
  - a signed-in user who is not the admin is told so by e-mail (`SignInGate`, from `/api/me`), so they never meet a page of 403s; a 503 offers a retry;
  - a `useMe` query feeds the top bar with the e-mail.
  - Update `src/test/harness.tsx` and the tests that set the token.
  - EN/ES copy, with ES in "usted".
  - The fixture config (`vite.fixture.config.ts`, the owner's file) is not committed. If it needs `/api/me`, tell the owner what to add.

### Owner-run (production)

- [x] A.12 Before the deploy:
  - read the Access team domain and the application's AUD tag in Zero Trust;
  - add `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD` and `ADMIN_EMAIL` to the VPS `.env` with nano;
  - take a fresh backup, and rehearse 0029 on a throwaway restore.
- [x] A.13 Deploy:
  - pull as `strategy`, `alembic upgrade head`, restart both services;
  - pps.6 for the panel;
  - check: the panel loads with no token prompt, `GET /api/me` shows the owner as admin, `users` holds exactly the owner's row, and the webhook still answers;
  - then remove `ADMIN_API_TOKEN` from `.env` and restart the API.

### Delivery

- [x] A.D.1 Gate (backend and frontend), and an independent verifier over the whole PR.
- [x] A.D.2 Push and open the PR (on the owner's word).
- [x] A.D.3 Merge (owner), with a merge commit.
- [x] A.D.4 Deploy (A.12, A.13).
- [x] A.D.5 Delivery log row and "Production now".

### PR A's delivery

**Verification (A.D.1).** Gate on `c9dc960`: backend ruff and mypy clean (315 files), full pytest exit 0; frontend lint clean, vitest 2917 passed. An independent verifier read A.1-A.11 against the diff and found two blockers, both fixed in `7f878ca`:
- a failed fetch of the Access keys turned the next minute of requests into 401 instead of 503, so the panel read an outage as an expired session;
- a 403 test for a signed-in non-admin existed for one router only. It now covers every admin-only route, by method and path. It was proven non-vacuous by stripping the pools router's guard in memory, from a script outside the repository: both route-guard tests failed, and passed with the guard back. (Editing the guard out of the source was refused by the session's permission classifier.)

The same commit adds one WARNING, naming the failed check and never the token or a claim, when a presented assertion is refused: behind the tunnel that means `ACCESS_AUD` or `ACCESS_TEAM_DOMAIN` is wrong. Advisories left open: a rotated key can be refused for up to a minute; the dev identity is stopped by the startup invariant only, not per request; the old token stays in the browser's `localStorage`, unused.

**PR A's deploy, 2026-10-22** (owner-run, one step at a time):
1. Pull as `strategy`, fast-forward `7a006fc..a1295e0`.
2. `uv sync --locked` as `strategy`: `+ pyjwt==2.15.1`. The services start with `uv run`, which would sync too, but a failure here shows while they still run.
3. Backup `/root/sm_pre0029_20261022_0051.dump`. Rehearsal on `sm_rehearsal_0029`: production at `0028`; `strategies` 6, `signals` 44, `ledger_entries` 42 on both sides and unchanged by the upgrade; after `upgrade head`, `0029`, `users` empty with `ck_users_email_normalized`, `users_pkey`, `ux_users_email`; a mixed-case e-mail refused; `downgrade -1` back to `0028` with `users` gone; the copy dropped.
4. `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD` and `ADMIN_EMAIL` added with nano. A read-only check ran the startup invariant against the real `.env`: ok, `dry_run` false, no dev identity, the team domain a `cloudflareaccess.com` host, the AUD 64 hex characters.
5. `alembic upgrade head`: `0028 -> 0029`.
6. Both services restarted, both active.
7. pps.6: bundle built from a clean worktree of `origin/main`, 22 entries, SHA-256 `369aadcaac8b5f9e6ec40f1c50fc95c994e8b1b7c0801ae2e9a8a1e55e808840`; `OK`, `readable`, bundle and checkout both `a1295e08340b`.
8. Checks: the panel opens with no token prompt and shows the owner's e-mail; `/api/me` answers the owner with `is_admin` true and `dry_run` false; `users` holds one row, and it is `ADMIN_EMAIL`; no WARNING or ERROR from the API since the restart; a POST to `/webhook/tradingview` from the VPS answers `401` (a GET answers `404` from Caddy's path filter, as since whn.3, and proves nothing).
9. `ADMIN_API_TOKEN` removed from `.env` (owner `strategy`, mode 600 before and after); the API restarted, active, and the panel still opens.

## PR B: ownership, scoping, the worker per user

Design AD2, AD8, AD9, AD10, and decision 16. Written 2026-10-21 from production at `0029` and a read-only map of the code. Paths are relative to `backend/src/strategy_manager/`.

Every owned row gets its owner, and every read of owned rows takes `user_id`. Keys, pools, performance and open positions open to any signed-in user, scoped. Strategies, the pair catalogue, the webhook secret and origin, and discrepancies stay admin-only (decision 16). Until PR C, a signal is worked in its strategy author's pools, with the author's key.

**Risk:**
- item 1: migration 0030 rewrites keys and constraints on live tables;
- item 2: guards change from admin-only to scoped;
- item 4: the advisory lock's key changes.

It needs an independent verifier before the PR.

### Backend

- [x] B.1 Migration 0030 (design AD2, "Migration plan"). Done on 2026-10-21:
  - 22 tests in `tests/migrations/test_0030_ownership.py`. Two mutations proved them non-vacuous: rewriting the ledger, and a pool FK without `user_id`.
  - The tests of 0020-0028 now migrate to `0029`, the revision they were written against.
  - **Gate red by the owner's choice:** 132 tests in 16 files stay red until B.3 and B.9. All of them run on the `head` schema and exercise code that does not write `user_id` yet. Nothing is pushed until the gate is green.
  - Specification:
  - **Refusals.** With rows to own, it refuses unless `users` holds exactly one row, and names the count. That row is the owner of every existing row.
    - A database nobody has signed into holds only the four pools `0003` seeded. Those pools are deleted, since saving a key creates its pool again. Without this, every fresh database (tests, a new machine) would be refused.
  - **`user_id uuid NOT NULL REFERENCES users(id)`** on `exchange_credentials`, `capital_pools`, `pool_balance_snapshots`, `reservations`, `execution_attempts`, `ledger_entries`, `reconciliation_discrepancies` and `booking_proposals`, each with an index. `strategies` gets `author_id` the same way.
    - Every table takes the owner's id as a constant `DEFAULT`, dropped in the same migration. No row is rewritten. The ledger is never UPDATEd, and its append-only triggers stay enabled.
  - **Pools.** `capital_pools` gets `id integer GENERATED ALWAYS AS IDENTITY` as its primary key, plus `UNIQUE (user_id, exchange, venue, settlement_currency)` and `UNIQUE (id, user_id)`.
    - The four composite pool FKs are dropped first: reservations, snapshots, discrepancies, booking proposals.
    - Each of those tables gets `pool_id`, filled by a join and then made `NOT NULL`. Its FK is `(pool_id, user_id)` to `capital_pools (id, user_id)`, so the database refuses one user's row in another user's pool. The snapshots' cascade is kept.
    - `pool_balance_snapshots`' primary key moves to `pool_id`.
    - The text columns `exchange`, `venue` and `settlement_currency` stay where they are.
  - **Strategies.** `fk_strategies_capital_pool` is dropped. A CHECK limits `venue` and `settlement_currency` to the values `capital_pools` allows.
  - **Uniques that gain `user_id`:**
    - `ux_exchange_credentials_one_active_per_exchange` becomes `(user_id, exchange) WHERE is_active`;
    - `ux_ledger_exchange_fill` becomes `(user_id, exchange, venue, exchange_fill_id)`;
    - `ux_reconciliation_open_per_symbol` gains `user_id`.
    - The names stay, because code catches them by name (`accounts/infrastructure/credential_vault.py:38`, `reconciliation/infrastructure/booking_writer.py:44`).
    - The `ON CONFLICT` targets that list the old columns need `user_id`, so they move with B.3:
      - `accounts/infrastructure/capital_pool_writer.py:49`;
      - `accounts/infrastructure/balance_snapshot_repository.py:42`;
      - `reconciliation/infrastructure/repository.py:137`.
  - **Downgrade.** It refuses unless exactly one user exists, then restores 0029's keys and constraints.
  - **Tests** on real PostgreSQL:
    - upgrade with one user: every row is the owner's, and the ledger rows keep their `xmin`, so none was rewritten;
    - the refusal with zero users and with two;
    - a second user may hold an active key on the same exchange and the same pool triple;
    - the downgrade and the upgrade again.
- [x] B.2 The `current_user` dependency returns the `User` (through `ResolveUser`) for `verified_email`. `/api/me` uses it instead of resolving inline. `require_admin` is unchanged.
- [x] B.3 Scoped persistence (AD8): every repository and adapter that reads or writes owned rows takes `user_id` and filters on it. That covers the accounts, allocation, execution, ledger, reconciliation, performance and strategies adapters in the map of 2026-10-21. No unscoped read remains outside an admin use case or the worker's per-user loop. Each scoped method gets one test where a second user's row is present and not returned.
  - Done in one unit per table:
    - `9416441` strategies;
    - `b5e69b3` pools and snapshots;
    - `b84bace` keys and the worker per pair;
    - `7b54c41` reservations;
    - `e9cf2f3` execution attempts;
    - `43e6372` ledger;
    - `4564300` discrepancies and proposals;
    - `20b71ef` reconciliation per user;
    - `e460b3e` performance.
  - The red baseline at `1a8201d` was 309 failing tests, not 132: the 132 counted FAILED only and left out ERROR. After `e460b3e` the full backend suite is green, with ruff and mypy clean (2026-10-26).
  - Global by design, for admin use cases and worker sweeps:
    - the strategy list;
    - the per-strategy counts and lists behind archive and delete;
    - `expire_due` and `expire_pending`;
    - the failed-job signal reader;
    - the worker's startup mode check (`SqlAlchemyModeOriginReader` without a user);
    - the admin discrepancy list;
    - `get_for_update` and the auto-booking sweeps, which take the user from the proposal itself;
    - `signal_owner` and `attempt_owner` (`job_owner.py`), which find the user a worker job runs as.
  - Two filters are defense in depth and not provable by mutation, because the ledger filter beside them already excludes the other user's rows: the reservation filter in `allocation_fills_source` and the ledger filter in `position_facts`.
- [x] B.4 The advisory lock identifies one user's pool. Two users with the same `(exchange, venue, settlement_currency)` never share a lock: proven with the lock-hold harness (`not task.done()` for the same user, done for the other). `assert_pool_lock_keys_distinct` covers every user's pools, or becomes unnecessary if the key is the pool's id. The lock order stays pool lock first, then row locks.
  - **How the key is built.** `LockKey` carries `user_id` and folds it into the second hash input, as `settlement_currency:user_id`. The nil UUID is refused.
  - **Why not the pool's id.** The callers hold the market and the user, not the pool row. Also, `recurring_jobs` takes single-bigint locks that small pool ids could collide with.
  - **Where each caller gets the user:**
    - `AllocateCapital`: the strategy's author.
    - Archive and delete strategy: the strategy's author.
    - `DeleteCredential`: the deleting user.
    - The startup invariant: each `PoolConfig.user_id`, over every user's enabled pools.
  - **Tests.** `tests/allocation/infrastructure/test_pool_lock_per_user.py` checks that the same user waits while another user and a third user complete. Each call site's user is proven by a fixed-UUID mutation.
  - **Why it was needed.** Before this, two users on one market made the startup invariant refuse to start.
- [x] B.5 Signal processing: a signal is allocated and executed in its strategy author's pool, with the author's key. Its reservation, execution attempt and ledger rows carry the author's `user_id`. The holding guard reads that user's holdings.
  - Done inside U1-U5 and confirmed by the verifier (B.D.1).
  - `ProcessSignalHandler` passes `policy.author_id` to the capability check, the holding guard, the balance read and `PlaceCommand.user_id`. `AllocateCapital` reserves with it.
  - The worker finds the job's user through `signal_owner` or `attempt_owner` before `exchange_for`.
  - `test_the_capability_asked_about_is_the_strategy_authors_key` was proven by an in-memory mutation: the author's id swapped for another turns it red.
- [x] B.6 Routers (decision 16):
  - credentials, pools, performance and open positions depend on `current_user` and pass its id down;
  - the other routers keep `require_admin`, and strategies stamp `author_id` from the admin's `User`.
  - `test_every_api_route_is_guarded.py` lists the scoped routes explicitly, and every other `/api` route still forbids a non-admin with 403.
  - **Cross-user tests**, one per scoped endpoint: user B asks for user A's resource and receives 404, or an empty list. No row changes, which includes B's DELETE leaving A's key active.
  - **What was done.** The four routers now take `dependencies=[Depends(current_user)]` in place of `require_admin`. An unsigned or forged request is still 401.
  - **Strategies.** They already stamped `author_id=user.id` (U1), so they needed no change.
  - **The scoped routes**, 9 of them, as `SCOPED_TO_THE_SIGNED_IN_USER` in the guard test:
    - `PUT`, `GET` and `DELETE` on credentials;
    - `GET /api/pools`;
    - the pool report, the strategy report, the trades and the fills under performance;
    - `GET /api/positions/open`.
  - **The guard test** checks that this set equals exactly the `/api` routes without `require_admin`, in both directions.
  - **Cross-user tests** use a real non-admin created by `current_user` (`OTHER_HEADERS`):
    - credentials list, delete and save;
    - pools list;
    - performance;
    - open positions.

    Each was red on a 403 before the swap and is proven by a mutation of its scoping filter. There is no pool update endpoint.
  - **Production.** Unchanged until Access admits another user.
- [x] B.7 Worker per `(user_id, exchange)` (AD9):
  - `read_key_coverage` returns sets of pairs, in one statement;
  - one `SyncBalances` per pair with an active key;
  - `_degraded` is keyed by the pair, and one user's failure degrades only that user;
  - `exchange_for`, the balance reader and the venue reader load the key of the row's user.
  - The startup refusal on a key that does not open is unchanged.
  - A Telegram alert names the user's id prefix, never an e-mail.
  - Done in `b84bace` (U2b) and confirmed by the verifier (B.D.1):
    - `read_key_coverage` is one `UNION ALL` statement;
    - a pair whose key does not open is skipped with a WARNING, and the other pairs still sync;
    - every alert and log names `str(user_id)[:8]`, and none names an e-mail.
- [x] B.8 Reconciliation per user's pool (AD10):
  - the venue's net position is read with that user's key;
  - the ledger side is filtered by `user_id`;
  - discrepancies and booking proposals carry it, and the admin's discrepancy view shows the user's e-mail beside each row.
  - Commits:
    - `4564300` gives discrepancies and proposals their user and pool;
    - `20b71ef` adds `ScanUsers`, which runs one `ScanPools` per user with that user's key. Prepare reads each discrepancy with its own user's fill reader, and `DiscrepancyView.user_email` is joined in one query. The interim `_reconciliation_key_holder` is removed.
  - A user with a pool but no key is skipped on that exchange with a WARNING on every scan cycle. The other users still scan.
  - The panel rendering of the e-mail is B.10.
  - **Correction, found while doing B.10.** `20b71ef` put `user_email` only on `GET /reconciliation/discrepancies`, but the panel reads `GET /reconciliation/confirmed`.
    - `ConfirmedDiscrepancy` now carries `user_id`.
    - Both routes look up the users' e-mails through one shared helper (`_user_emails`), in one query.
    - The query runs even when no item needs it, so `/confirmed` stays at a constant 4 statements, for one discrepancy or twenty.
    - The booked list carries no e-mail: B.10 asks for discrepancy rows only.
- [x] B.9 Tests: one fixture creates the owner's `User`, and the suites that insert owned rows directly pass its id (about 100 files).
  - `backend/tests/owner.py` (`OWNER_ID`, `seed_owner`, `seed_pool`, `seed_other_user` and others).
  - `tests/identity_auth.py` `act_as`, which signs a router test in as the fixtures' owner and keeps the real `require_admin`.
  - Seeds were updated unit by unit with B.3.

### Frontend

- [x] B.10 Discrepancy rows show the user's e-mail (B.8), with EN/ES copy, ES in "usted". Nothing else changes: `SignInGate` still stops a non-admin, because the pages a user can use arrive with PR C and later.
  - `DiscrepancyItem` shows a "User" / "Usuario" fact for both variants.
  - `fetchConfirmed` refuses a whole body whose discrepancy lacks `user_email`, the same as for every other field.
  - Tests: two in `DiscrepancyItem.test.tsx`, one in `discrepancies.test.ts`. All three were red before the code.

### Owner-run (production)

- [x] B.11 Before the deploy: a fresh backup, then rehearse 0030 on a throwaway restore.
  - counts per owned table, unchanged;
  - every `user_id` and `author_id` the owner's;
  - the ledger's `xmin` unchanged;
  - the new constraints present;
  - downgrade to `0029`, then upgrade again.
- [x] B.12 Deploy:
  - pull as `strategy`;
  - `alembic upgrade head`;
  - restart both services;
  - pps.6 for the panel.
  - Check:
    - the panel and every page load as before;
    - one balance sync per exchange in the worker's log, with no new WARNING or ERROR;
    - a reconciliation scan runs clean;
    - the webhook still answers.

### Delivery

- [x] B.D.1 Gate (backend and frontend), and an independent verifier over the whole PR. After `814f1eb`: ruff 0, mypy 0, pytest exit 0 with no failing test; frontend lint 0, vitest 2,920 passed.
  - **Verifier, 2026-10-26.** B.1-B.9 pass. B.10 is frontend and was outside its brief; the parent's frontend lint and tests are green. It found one blocker:
    - The scoped `DELETE /api/credentials/{exchange}` read enabled strategies for the whole market. A non-admin with their own key got a 409 that named the admin's strategy id and name, and could not delete the key while anyone had an enabled strategy on that market.
    - Fixed: `PoolExposureAdapter` filters `StrategyRow.author_id`. The regression test is `test_cross_user_b_delete_of_their_own_key_is_neither_blocked_by_nor_told_of_a_strategies`, red on the 409 before the fix. Two older delete tests now seed their strategy as the signed-in admin.
  - **Advisories, not fixed in PR B:**
    - `performance_router._strategy_pool` answers 404 for an unknown strategy id and 200 with empty figures for a real one, to any signed-in user. That reveals whether an id exists, but no figures or names.
    - Reconciliation scan and prepare build each user's readers with `vault.load` outside a per-user `try`. A key deleted between the coverage read and the load raises before the successor job is enqueued, which stops the chain for every user. `balance.sync` isolates each pair. The race is narrow, and the same failure existed with one key at the baseline.
- [x] B.D.2 Push and open the PR (on the owner's word): #86, on "Dale, push y PR".
- [x] B.D.3 Merge (owner), with a merge commit: `5632e76`.
- [x] B.D.4 Deploy (B.11, B.12).
- [x] B.D.5 Delivery log row and "Production now".

### PR B's delivery

**PR B's deploy, 2026-10-27** (owner-run, one step at a time):
1. Pull as `strategy`, fast-forward `a1295e0..5632e76`. No dependency changed, so no `uv sync`.
2. **Backup and rehearsal (B.11).** The backup is `/root/sm_pre0030_20261027_1356.dump`, and the rehearsal ran on `sm_rehearsal_0030`, restored from it.
   - Production was at `0029`, with 1 user.
   - Counts, the same in production and in the copy, and unchanged after `upgrade head`, after `downgrade -1` and after the second upgrade:
     - `exchange_credentials` 8, `capital_pools` 5, `pool_balance_snapshots` 2;
     - `reservations` 10, `execution_attempts` 20, `ledger_entries` 65;
     - `reconciliation_discrepancies` 1, `booking_proposals` 0;
     - `strategies` 6, `signals` 48.
   - The ledger's `(id, xmin)` fingerprint was unchanged by the upgrade.
   - Every `user_id` and `author_id` was the owner's.
   - Present:
     - `ck_strategies_venue`, `fk_strategies_author`;
     - the four `fk_*_capital_pool`;
     - `ux_capital_pools_id_user`, `ux_capital_pools_user_market`.
   - Both ledger triggers stayed enabled (`O`).
   - The copy was dropped.
   - The first two runs stopped on two bugs in the rehearsal script itself, before and after the upgrade of the copy, and never touched production. The second run left the copy at `0030`, and a follow-up script finished from there.
3. The worker was stopped (`inactive`) before the migration. The old code writes no `user_id`, which 0030 makes `NOT NULL`. The API stayed up, because ingress writes only `signals`.
4. `alembic upgrade head`: `0029 -> 0030`.
5. Both services restarted, both `active`.
6. **pps.6.** The bundle was built from a clean worktree of `origin/main` at `5632e763deb5`: `npm ci` 0, build 0, 22 entries, SHA-256 `a2c00a3e80d4be674344661bcab758eccc8e90d76613c7154492057f1772ab5e`. The VPS printed `OK`, `readable`, and `5632e763deb5` for both bundle and checkout.
7. **Checks.**
   - No WARNING or ERROR from either service since the restart. The two lines the grep counted are the INFO "operator alerts are on: ERROR and above..." line.
   - The worker logged:
     - `1 enabled pools, dry_run=False`;
     - `vault self-test: 1 sealed credential(s) opened (binance of user a90b5f44)`, which names the user's id prefix and no e-mail (B.7);
     - `recurring chains already alive`;
     - the watchdog: every enabled pool fresh, every chain scheduled, nothing failed.
   - A POST to `/webhook/tradingview` answered `401`.
   - The owner loaded every page of the panel. Discrepancies is empty: its one row is `OBSERVED` and resolved, and the view lists only open, confirmed ones.

## PR C: subscriptions and fan-out

Design AD3-AD5 and decision 18. Written 2026-10-27 from production at `0030` (main `7f67fc3`), a read-only map of the code, and a read-only pre-check of production. Paths are relative to `backend/src/strategy_manager/`.

A subscription becomes the only way to trade a strategy, the author included. One signal fans out into one delivery per eligible subscription, and each delivery is worked in its subscriber's pool, with the subscriber's key and share. Strategies stay admin-only until PR D (decision 16). Subscribing opens to any signed-in user, but a non-admin has no list of strategies to pick from until PR F, so production does not change in practice.

**Production at planning (pre-check, 2026-10-27):**
- 6 strategies, all on `binance/usdt-m/USDT`, each with exactly one pool of its author for that market:
  - 3 enabled, not archived, at 30 %: AAVE, SFP and STX "4h - RSI Divergences";
  - 3 disabled and archived, at 5 %: the three "... Test".
- 48 signals: 17 `ACCEPTED`, 16 `PROCESSED`, 15 `REJECTED`. None lacks its strategy.
- 10 reservations, all `FILLED`.
- 4 execution attempts have no `signal_id`. They predate 0025.
- The `jobs` table holds only finished signal jobs: 7 `DONE`, 4 `FAILED`.

**What the map found that the design did not say** (each is resolved in the tasks below):
- **a.** The position is kept per (strategy, symbol) (`signals/infrastructure/repository.py:108`). AD4's arming read the whole strategy. Decision 18 resolves this.
- **b.** A close works the prior signal's reservation (`signals/infrastructure/signal_context.py:77`). Per delivery, it has to work that subscription's open reservation for the symbol (C.6).
- **c.** The worker is serial. It claims one job at a time (`shared/infrastructure/worker_runner.py:32`, `job_queue.py` `.limit(1)`), and one runner is started (`worker.py:256`). AD5 called this unverified. Readiness D.3 now plans the concurrency change instead of discovering it.
- **d.** Every outcome write locks the signals row `FOR UPDATE` (`signals/infrastructure/outcome_repository.py:71`). All its writers move to the delivery (C.7).
- **e.** Archive and delete take only the author's pool lock (`strategies/application/archive_strategy.py:163`, `delete_strategy.py:118`). A subscriber's opening in another pool is not serialized against them (C.9).
- **f.** `signal.process` has no `dedupe_key` (`signals/application/ingest_signal.py:98-103`). Only the new `delivery.process` jobs get one.
- **g.** More code reaches one execution through `signal_id` than AD5 listed:
  - `execution_attempts.signal_id`;
  - `CloseOrphans` (`signals/application/close_orphans.py:197`);
  - `failed_job_signal_reader.py`;
  - `performance/infrastructure/rehearsal_pricing_source.py:65`;
  - the history count that blocks delete.

  All of them are covered by C.8.

**Deploy shape: expand now, contract later.**
- No column that the running code reads is dropped in 0031 or 0032.
  - `strategies.allocation_percent` becomes nullable and unused.
  - `signals.status`, `outcome_reason`, `outcome_detail` and `decided_at` stay in place. After C.7 they hold the strategy-level refusals that reached no delivery (archived strategy, nothing to close, nobody subscribed, an exhausted fan-out), and are not dropped. Only `strategies.allocation_percent` is still dropped, by a later migration (planned for PR D's 0033), once no deployed code touches it.
- The API's old code can then keep ingesting through the migration. Only the worker is stopped, as in PR B, because `reservations.delivery_id` becomes `NOT NULL` and the old worker does not write it.

**Assumption, stated rather than asked:** creating a strategy creates the author's ACTIVE subscription at the share the form sends, in the same transaction. Today, creating a strategy with a share means trading it, and this keeps that behaviour. PR D, which opens authoring to everyone, may revisit it.

**Risk:**
- item 1: two migrations move live data;
- item 4: the fan-out, the per-delivery lock and archive's locks.

It needs an independent verifier before the PR.

### Backend

- [x] C.1 Migration 0031, `subscriptions` (AD3; decision 18 drops `armed_at`). Done on 2026-10-27, with the gate green: ruff 0, mypy 0, full pytest exit 0 with no failing test.
  - 22 migration tests in `tests/migrations/test_0031_subscriptions.py`. Mutations proved each guard non-vacuous:
    - the trigger, both on insert and on update;
    - the no-pool refusal;
    - the author in the refusal and in the backfill join;
    - both CHECKs and the partial unique, where LEAVING counts as live;
    - the pool FK without `user_id`;
    - both downgrade refusals;
    - the cascade.
  - The writers' first RED was a missing table, not an assertion. The mutations above are the proof that stands in for it.
  - Two additions beyond the text:
    - the backfill copies the strategy's `created_at`;
    - the downgrade also refuses a strategy that has no share and no subscription.
  - Decision 19 came from `test_strategy_references_guard`: `StrategyHistory.subscriptions` counts and never blocks. `SubscriptionRow` mirrors 0031 for ORM-built schemas. The adapter counts directly until C.4 adds a repository.
  - Not changed: the `StrategyRow` model still declares `allocation_percent` `NOT NULL`. Every write still sets it, and C.4 removes it from the model.
  - Columns: `id uuid pk`, `user_id`, `strategy_id`, `pool_id`, `allocation_percent numeric` with CHECK `> 0 AND <= 100`, `status` CHECK in `ACTIVE | LEAVING | ENDED`, `created_at`, `left_at`, `ended_at`.
  - Constraints:
    - FK `(pool_id, user_id)` to `capital_pools (id, user_id)`, so the database refuses one user's subscription in another user's pool;
    - FK to `users`, and FK to `strategies` `ON DELETE CASCADE` (decision 19). `StrategyHistory` gains a `subscriptions` count that never blocks, in the response body and the delete log, like `enablement_events`. `COUNTED_STRATEGY_REFERENCES` gains the key;
    - partial unique `(user_id, strategy_id) WHERE status <> 'ENDED'`;
    - indexes on `user_id` and `strategy_id`.
  - A trigger refuses a row whose pool's `(exchange, venue, settlement_currency)` differs from its strategy's. That holds on insert, and on an update of `pool_id` or `strategy_id`.
  - Backfill: one subscription per strategy, for its `author_id`, in that author's pool for the strategy's market, at the strategy's `allocation_percent`.
    - It is ACTIVE when the strategy is not archived. It is ENDED, with `ended_at = archived_at`, when it is.
    - It refuses, naming the strategy, when the author has no pool or more than one for that market. Production has exactly one for each of the 6.
  - `strategies.allocation_percent` becomes nullable. Its CHECK stays; it is no longer read or written (expand and contract, above).
  - Downgrade: refuses unless exactly one user exists, then copies each strategy's share back from its latest subscription and drops the table.
  - Tests on real PostgreSQL, through `migrated_database(name, "0030")` (`tests/pg_head_schema.py:101`):
    - the backfill, with both ACTIVE and ENDED;
    - the refusal with no pool;
    - the cross-user pool FK and the market trigger;
    - the partial unique: a second ACTIVE row is refused, while a new row after ENDED is allowed;
    - the downgrade and the upgrade again.
- [x] C.2 Migration 0032, `signal_deliveries` (AD5). Done on 2026-10-27.
  - 21 migration tests are in `tests/migrations/test_0032_signal_deliveries.py`. On a no-op skeleton they failed on assertions, except for two that guard something already true: the signals keep their outcome columns, and the `reservations.signal_id` unique stays. Those two were proven by mutation.
  - Mutations proved each guard non-vacuous:
    - the refusal;
    - picking the author's subscription;
    - the `reservations.delivery_id` unique;
    - the downgrade's user guard.
  - Added beyond the text: each attempt takes its delivery from its own `signal_id` first. Only an attempt written before 0025 falls back to the reservation it opened, or to the one it closed. The writer had left closing attempts with no delivery. Three tests went red on assertions before the fix: the closing attempt, the pre-0025 closing attempt, and every attempt having a delivery.
  - The delivery's `created_at` is the signal's `received_at`.
  - The full gate found two things:
    - The downgrade refused an empty database, which broke `test_0029_users`' downgrade of the whole chain. It now refuses only with more than one user, as 0031's does. The test was red first.
    - `test_strategy_references_guard` saw the new FK from `execution_attempts` to `signal_deliveries`. It is not a new way to a strategy: an attempt that carries a delivery also carries its signal or a reservation of that signal, and the history counts those. The guard now names that FK. C.8 must keep writing `execution_attempts.signal_id` beside `delivery_id` for this to stay true.
  - The ORM mirrors 0032: `SignalDeliveryRow` is new, and `ReservationRow` and `ExecutionAttemptRow` gain `delivery_id`.
  - Columns: `id uuid pk`, `signal_id`, `subscription_id`, `user_id`, `status` (default `ACCEPTED`), `outcome_reason`, `outcome_detail`, `decided_at`, `created_at`.
  - Constraints: `UNIQUE (signal_id, subscription_id)`, an index on `user_id`, and FKs to `signals`, `subscriptions` and `users`.
  - Backfill: one delivery per existing signal, for its strategy author's subscription from 0031. Each delivery copies the signal's `status`, `outcome_reason`, `outcome_detail` and `decided_at`.
  - `reservations.delivery_id uuid`, FK to `signal_deliveries`, `UNIQUE`. It is filled through `reservations.signal_id`.
    - It stays NULLABLE here, and C.6 adds `NOT NULL` to this same migration, together with the code that writes it (owner's choice, 2026-10-27). Until C.6 the reservation repository does not write it, so a `NOT NULL` now would turn every test that reserves on the head schema red. 0032 is not in production, so editing it is safe. The deploy shape does not change.
    - The column-level unique on `reservations.signal_id` (from 0004, default name, nothing catches it by name) stays until C.6 too. While `delivery_id` can be NULL, its `UNIQUE` refuses nothing, so dropping the old one here would leave the head schema with no guard against a second reservation for one signal. C.6 drops it, in this same migration, when two subscribers first get a reservation each for one signal. The column itself stays.
  - `execution_attempts.delivery_id uuid NULL`, FK to `signal_deliveries`. It is filled through the attempt's reservation, because 4 production rows have no `signal_id`.
  - The signals' outcome columns are copied, not dropped.
  - Downgrade: refuses unless exactly one user exists, then restores the `signal_id` unique and drops the new columns and the table.
  - Tests:
    - every signal has exactly one delivery;
    - the outcome columns are equal to the signal's;
    - every reservation's `delivery_id` matches its signal's delivery;
    - an attempt without `signal_id` still gets its delivery through its reservation;
    - the downgrade and the upgrade again.
- [x] C.3 `subscriptions/domain`: the `Subscription` aggregate (a new top-level module, by the screaming rule). Done on 2026-10-27, with `leave(now)` and `end(now)`.
  - 7 tests are in `tests/subscriptions/domain/test_subscription.py`, and 6 of them were red on assertions against a no-op skeleton.
  - The default-status test passed at once. A mutation, a default of LEAVING, first stayed green because the test passed the status explicitly. The test was fixed to build the default, and then the mutation turned it red.
  - A LEAVING subscription that ends keeps its `left_at`.
  - The states are ACTIVE, LEAVING and ENDED. The legal moves are ACTIVE to LEAVING, ACTIVE to ENDED and LEAVING to ENDED; any other raises.
  - The share reuses the strategies domain's `AllocationPercent`.
  - Pure unit tests.
- [x] C.4 `subscriptions/application` and `infrastructure`: the use cases `Subscribe`, `Leave` and `ChangeShare`, a repository scoped by `user_id`, and a router under `/api/subscriptions` open to any signed-in user.
  - **Subscribe** needs:
    - a strategy that exists and is not archived;
    - the user's own pool for the strategy's market, or 409 `NO_POOL_FOR_MARKET`;
    - no non-ENDED subscription of that user to that strategy, or 409.
  - **Leave** runs under that user's pool lock. It sets LEAVING when the user holds an open allocation of the strategy, and ENDED otherwise (decision 4).
  - **ChangeShare** is refused unless the subscription is ACTIVE.
  - A user can list their own subscriptions.
  - Another user's subscription answers 404 (AD8), with a cross-user test for each route, and no row changes.
  - **Strategies:**
    - `RegisterStrategy` creates the author's subscription in the same transaction (assumption above).
    - `UpdateStrategy` and `StrategyView` lose `allocation_percent`. The view gains the signed-in user's subscription for that strategy, or null.
    - The share preview (`strategies/infrastructure/router.py:522`) previews against the signed-in user's pool.
  - Done in two units:
    - **C.4a** is the subscriptions module: the use cases, repository and router. Done on 2026-10-27.
      - **Routes:**
        - `POST /api/subscriptions` answers 201. Its refusals are 404, 409 `STRATEGY_ARCHIVED`, `NO_POOL_FOR_MARKET` and `ALREADY_SUBSCRIBED` (the unique index's race included), and 422.
        - `GET /api/subscriptions` lists only the user's own subscriptions.
        - `POST /api/subscriptions/{id}/leave` sets LEAVING or ENDED. It answers 409 `SUBSCRIPTION_NOT_ACTIVE` when the subscription is not active.
        - `PATCH /api/subscriptions/{id}` answers 409 `SUBSCRIPTION_NOT_ACTIVE` when the subscription is not active, and 422 for a bad share.
      - "Holds an open allocation" counts the user's ledger holdings of the strategy, under every spelling of the symbol, plus a live (PENDING or SUBMITTED) reservation. It is the archive's exposure question, asked for one user.
      - **RED:**
        - The router tests failed on assertions against a skeleton that answered 501.
        - The 422 tests pass on pydantic before the handler runs, so they were proven by mutating the body type.
        - Mutations proved each of these guards: the lock, the user filter on get, `get_for_update` and update, `has_live`, the race translation, and the user filter on reservations.
        - Not mutation-proved: the user argument passed to the ledger's `symbol_holdings`. `test_another_users_open_allocation_does_not_keep_this_user_leaving` covers it.
      - The full gate found that `test_webhook_secret_router`'s sweep had no body for the new write routes and no data for the list. It now seeds the admin's subscription, and it sends real bodies to POST and PATCH. Leave is in `_NO_BODY`.
    - **C.4b** is the strategies side above. It needs C.4a's repository. Done on 2026-10-27 in `cb15718`, with the full gate green: ruff 0, mypy 0, pytest exit 0 with no failing test.
      - **What changed:**
        - `RegisterStrategy` takes an `AuthorSubscriptionPort` (strategies declares it, `SqlAlchemyAuthorSubscription` implements it over C.4a's repository and pool lookup). The author's ACTIVE subscription is flushed after the strategy insert and before the one commit, in the author's own pool, at the requested share. The strategy still gets its own `allocation_percent`.
        - The pool refusal was already there: `PoolNotAvailable` answers 422 before any write. It stays 422 (not 409 `NO_POOL_FOR_MARKET`). The adapter raises the same error for a pool deleted after that check, and the route rolls back, so neither row survives.
        - `UpdateCommand` and `UpdateRequest` lose `allocation_percent`. A PATCH body that carries the key (any value, `null` included) is refused with 422 located at `body.allocation_percent`; other unknown keys are still ignored as before. `UpdateStrategy` no longer writes the share or logs a share change.
        - `StrategyView` loses `allocation_percent` and gains `subscription`, C.4a's `SubscriptionView` or null, on every route that returns it (POST, GET list and detail, PATCH, PUT pairs, archive). The list reads it with one query (`live_for_strategies`).
        - The share preview reads the signed-in user's pool, not `strategy.author_id`'s.
      - **RED:**
        - Against skeletons that changed nothing, these failed on assertions: the register-order test, the failing-subscription test, the PATCH 422 tests, the no-share-on-any-view test, `UpdateCommand` has no share, the four `subscription` view tests, and the second-user preview.
        - The two adapter integration tests and `test_a_refused_registration_never_asks_for_a_subscription` were written after the code they guard. They were proven by mutation only.
      - **Mutations proved:**
        - the adapter doing nothing;
        - committing before the subscription;
        - asking for a subscription before the pool check;
        - `UpdateStrategy` rewriting the share;
        - the user filter on `live_for_strategies`;
        - its status filter;
        - a query per strategy on the list.
      - **Tests moved to the new contract, none dropped for other behavior:**
        - the PATCH-share tests in `test_router.py`, `test_share_decimals.py` and `test_update_strategy.py` now assert the refusal;
        - the share-change log tests and `test_share_change_integration.py`'s reservation and next-opening tests guarded the removed edit path, so C.6 re-homes them on `ChangeShare`. Its lock test now patches the name;
        - the delete tests expect `subscriptions: 1` for a registered strategy, since registration subscribes the author;
        - the preview tests sign in as `OWNER_ID` with `act_as`.
      - The share-change log line moved with the share: `ChangeShare` now logs a real change after its commit, with the subscription and strategy ids and both values. 3 tests are in `tests/subscriptions/application/test_change_share.py`. The positive one was red on an assertion first. The other two were proven by mutation: logging always, and logging before the commit.
      - The full gate found that `test_validation_errors`' redacted-422 test reached the local database. `PATCH /api/strategies/{id}` now resolves the signed-in user before it validates the body, so the test serves the app through `without_a_database`.
      - **Not mutation-proved:** the PUT-pairs and archive answers carrying `subscription` (the one `_view` helper is covered through GET, PATCH and POST).
      - **Left for later:**
        - A preview with no `share` query still defaults to the strategy's own copy of the share, not the caller's subscription. C.6 moves it with the sizing read.
        - A signed-in user with no pool on the strategy's market gets the preview's existing 500 and one ERROR log, written for a data fault. Only the admin reaches the strategies router today, and the admin's pools exist. It becomes a 4xx before that router opens to other users.
  - `strategies.allocation_percent` stays on the domain's `AllocationPolicy` and on `StrategyRow` until C.6. `process_signal` still sizes from it, and C.6 moves that read to the subscription. Until then `RegisterStrategy` writes the share to both the strategy and the author's subscription. Only the API stops exposing it on the strategy. The branch is never deployed in between, so the interim gap does not reach production: `ChangeShare` does not move sizing before C.6.
- [x] C.5 `FanOutSignal` (`signals/application`) replaces the body of the `signal.process` handler. In one transaction:
  1. archived refusal and effect classification, as today, per (strategy, symbol);
  2. a delivery for each eligible subscription, `INSERT ... ON CONFLICT (signal_id, subscription_id) DO NOTHING`;
  3. one `delivery.process` job per eligible delivery, through `enqueue_unique` with `dedupe_key` `delivery:<id>`. That includes a delivery that already existed: a `signal.process` job left queued across the deploy finds its signal's delivery made by the 0032 backfill, and enqueuing only for inserted rows would drop that signal without a log line.
  - **Eligibility (decision 18):**
    - an opening effect, or a reverse, goes to every ACTIVE subscription;
    - a closing effect goes to the ACTIVE or LEAVING subscriptions that hold that symbol's open allocation of the strategy;
    - for a reverse, a subscription that holds the allocation gets both halves, and one that does not gets only the opening half.
  - **Tests:**
    - a retried `signal.process` makes no second delivery and no second job;
    - a signal whose delivery already exists, as after the backfill, still gets its one `delivery.process` job;
    - an opening reaches all ACTIVE subscriptions and no LEAVING or ENDED one;
    - a close reaches only the holders;
    - a new subscriber gets the next opening of a symbol, but not the close of a position it never opened;
    - two users' symbols are spelled differently on each side of the boundary (working agreement).
  - Done on 2026-10-27, not ticked: the unit is built and tested but **not wired**.
    - **What was built:** `FanOutSignal` (`signals/application/fan_out_signal.py`, ports declared there), its adapters (`signals/infrastructure/fan_out_adapters.py`: `SignalFactsAdapter`, `SqlAlchemySubscribers`, `SqlAlchemyDeliveryRepository`) and `JobKind.DELIVERY_PROCESS`. One transaction, one commit at the end, no pool lock.
    - **Seam with C.6:** the `signal.process` handler still runs today's `ProcessSignalHandler`, and nothing registers a handler for `delivery.process`. Only `FanOutSignal` enqueues it. A `delivery.process` job with no handler would drop a signal, and an interim handler running the author-only body once per delivery would double it. C.6 wires both.
    - **Classification as today:** `PositionTransition.classify` over the same prior-signal lookup (`find_prior`), per (strategy, symbol), and the archived refusal with `ProcessSignalHandler`'s reason and text (`STRATEGY_ARCHIVED`). Nothing in that classification reads per user. The untradable-pool refusal stays with the delivery (C.6).
    - **Eligibility:** an opening goes to every ACTIVE subscription. A close goes to the ACTIVE or LEAVING subscriptions whose user holds that symbol's allocation: ledger holdings under every spelling (per allocation), or a PENDING/SUBMITTED reservation matched to the symbol through the signal that opened it (a reservation carries no symbol). Today's close keys on the prior signal's reservation of any status, so the ledger-or-live-reservation rule is the spec's, not today's.
    - **Reverse:** an ACTIVE holder gets both halves, an ACTIVE non-holder only the opening, and a LEAVING holder only the closing (a leaving subscription never opens). The last case composes the two stated rules; the spec text only names ACTIVE subscriptions for a reverse.
    - **Halves** travel in the job payload (`delivery_id`, `halves`: `open`, `close` or `close_and_open`), because `signal_deliveries` has no column for them (a migration was out of scope). They are what the fan-out transaction saw; C.6 still re-reads the user's holding.
    - **Nothing silent:** a signal with no eligible subscription logs one INFO line (signal id, reason) and ends `REJECTED` in the same commit, `NO_POSITION_TO_CLOSE` for a close nobody holds (decision 27's reason) and `NO_ACTIVE_SUBSCRIPTION` otherwise.
    - **RED:** the 12 tests (11 on PostgreSQL in `tests/signals/infrastructure/test_fan_out_integration.py`, 1 on fakes in `tests/signals/application/test_fan_out_signal.py`) all failed on assertions against a no-op `run`.
    - **Mutations proved:** ACTIVE filter widened to LEAVING; `_holds` always true; the reservation's symbol filter removed; the reservation's spelling set narrowed to the alert's own; ENDED added to the live statuses; the delivery read-back dropped (conflicts return nothing); a reverse giving every holder both halves; the archived guard off; the settle without its commit; the INFO trace removed; a second commit before the jobs.
    - **Added after review (2026-10-27):**
      - **Rule:** a subscription is eligible only if `subscriptions.created_at <= signals.received_at`, for an opening, a close and a reverse alike, so a new subscriber gets the NEXT opening on a retry or a late job too. The filter is in `SqlAlchemySubscribers._subscribers`; both `SubscribersPort` methods take `received_at`, and `SignalFacts` carries it.
      - **Test:** `test_a_subscription_created_after_the_signal_was_received_gets_nothing`, parametrized over opening, closing and reversing. A late holder and an early holder differ only by date. It was red on an assertion first (the late one was delivered to) in all three cases, then green with the filter.
      - **Reservation filters, mutation-proved:** the user filter (`test_another_users_live_reservation_on_the_symbol_does_not_make_this_user_a_holder`, which also turned red alongside the live-reservation test), the strategy filter (`test_a_live_reservation_of_another_strategy_does_not_make_a_holder`) and the status filter (`test_a_reservation_that_no_longer_holds_capital_does_not_make_a_holder`). The three tests passed at once; each went red when its filter was removed.
      - The fan-out tests now subscribe a day before the signals (`created_at` on `seeds.subscription`), since the signals carry fixed past dates.
    - **Not mutation-proved:** `terminal_at IS NULL` on the reservation branch; the order of the deliveries and jobs; the `<=` bound itself (equal timestamps).
- [x] C.6 `ProcessDelivery`, today's `ProcessSignalHandler` body taking a delivery. Each use of `policy.author_id` (`process_signal.py:500-778`, `allocate_capital.py:124-272`) becomes the delivery's `user_id`:
  - the pool is the subscription's pool;
  - the share is the subscription's `allocation_percent` (`process_signal.py:625-628`);
  - the key is the subscriber's: `job_owner.py` gains `delivery_owner`;
  - the prior reservation is that subscription's open reservation for the symbol, not the prior signal's (finding b);
  - the reservation is written with `delivery_id`, and 0032 is edited in the same unit (see C.2): `reservations.delivery_id` becomes `NOT NULL`, and the unique on `reservations.signal_id` is dropped. Migration tests: a reservation without `delivery_id` is refused, and two reservations for one signal on two deliveries are accepted;
  - in the same transaction, a LEAVING subscription whose last open allocation of the strategy closes becomes ENDED.
  - **Tests:**
    - two subscribers to one strategy, each sized from their own pool and share, each placed with their own key (the fake, per pool);
    - a close works only that subscriber's reservation;
    - LEAVING turns into ENDED on the last close;
    - re-homed from C.4b on `ChangeShare`: a share change leaves an already-held reservation as it is, and the next opening is sized at the new share;
    - a share preview with no `share` query defaults to the caller's subscription share;
    - a position opened before the upgrade, whose reservation got its `delivery_id` from the backfill, is closed by the first close signal after it. Production may hold an open position across the deploy.
    - C.6 wires both handlers together (C.5 left them unwired): `signal.process` runs `FanOutSignal` and `delivery.process` runs `ProcessDelivery`, with a test that proves each kind reaches its own handler. `ProcessDelivery` reads the `halves` of the job payload.
  - Done on 2026-10-28, not ticked. The unit was built in two sessions: the first was cut by a usage limit before its commit, so for everything it built the RED was not observed by the finisher and the proof below is by mutation (a temporary edit of the guarded code, seen red on an assertion, then reverted and seen green).
    - **What changed, per scope item:**
      1. **Wiring.** `signal.process` runs `FanOutSignal` (`main._build_fan_out_signal`, no exchange client, no key). `delivery.process` runs `ProcessDelivery` (`main._build_process_delivery`) with the client and keys of `job_owner.delivery_owner`, the delivery's own `user_id`. Tests: `test_main_job_owner_keys.py` (`test_a_signal_job_fans_out_its_signal_and_opens_no_venue_client`, `test_a_delivery_job_trades_with_the_subscribers_key_never_the_strategy_authors`, `test_the_owner_of_a_delivery_is_its_user_not_the_authors`).
      2. **One body.** `ProcessSignalHandler` became `ProcessDelivery(deliveries, ...).handle(delivery_id, raw_halves)`; there is no second copy. Every `policy.author_id` use is now `delivery.user_id` (capability, holding guard, balance refresh, sizing read, `AllocateCommand`, `PlaceCommand`, `latest_close_for`, `CloseCommand`, orphan close) and `AllocateCapital` takes `command.user_id` (resume lookup, pool lock, pool status, balance read, active sum, insert). `SignalContextAdapter.load(delivery)` reads `own_reservation` as the delivery's user. The share is the subscription's (`SqlAlchemyDeliveries` joins `subscriptions.allocation_percent`). The pool is the subscription's: the user's own on the strategy's market.
      3. **Halves.** `halves` comes from the job payload. A payload without a usable one (absent, not a string, not `open`/`close`/`close_and_open`) is refused with an ERROR log and `REJECTED` (`DELIVERY_HALVES_MISSING`); one the signal contradicts runs nothing (`DELIVERY_HALVES_MISMATCH`). Never defaulted.
      4. **Prior reservation.** `SqlAlchemySubscriptionReservations.latest_before` (`signals/infrastructure/delivery_adapters.py`): the subscription's own latest reservation, through its delivery, on this strategy and symbol under every spelling, for a signal received strictly before this one, in any status. None gives today's `NO_POSITION_TO_CLOSE`.
      5. **Reservations carry `delivery_id`.** `AllocateCommand.delivery_id`, `Reservation.delivery_id`, the repository writes it and refuses a reservation without one. Migration 0032: `reservations.delivery_id` NOT NULL after its backfill, the 0004 unique on `signal_id` dropped (its name found in `pg_constraint`, a missing one raises), the downgrade restores it. The ORM follows.
      6. **LEAVING to ENDED.** `SettleExecution` takes the user's pool lock first (after the remote read, before any row lock) when the attempt closes, books the fill, and then calls `EndLeavingSubscription.end_if_flat` in the same transaction. It reads the subscription `FOR UPDATE` (`get_live_for_update`), then the holding, and calls `Subscription.end`.
      7. **Exhausted job.** `SqlAlchemyFailedJobSignalReader` maps a `delivery.process` job to its delivery's signal, so an exhausted job is recorded against it as an exhausted `signal.process` is. A missing delivery is loud.
      8. **Re-homed from C.4b.** The share preview with no `share` query defaults to the signed-in user's live subscription share, and to the strategy's own copy when they hold none. A share change leaves a held reservation as it is, and the next opening is sized at the new share.
    - **Tests named in the brief:** `test_delivery_flow_integration.py` (two subscribers each sized from their own pool and share and placed on their own venue; a close works only that subscriber's reservation; a subscription with no prior reservation gets `NO_POSITION_TO_CLOSE` while the holders close; LEAVING to ENDED on the last close, and still LEAVING while another allocation is open; the share change), `test_pre_upgrade_position_integration.py` (a position opened at 0031, backfilled by the real `alembic upgrade head`, closed by the first close after it), `test_process_delivery.py` (the unit switches, the missing and contradicted halves), `test_subscription_reservations.py` (the prior lookup on PostgreSQL), `test_0032_signal_deliveries.py` (a reservation without `delivery_id` is refused; two reservations for one signal on two deliveries are accepted; no unique remains on `signal_id`; the downgrade restores it), `test_exhausted_jobs_integration.py` and `test_failed_job_signal_reader.py` (the exhausted delivery job).
    - **Interim gaps, left on purpose:**
      - **C.7 (closed by C.7):** outcomes stayed on the signal row, so two deliveries of one signal shared one terminal outcome and the second write was dropped. C.7 moved them to the delivery's row.
      - **C.8 (closed by C.8):** `signal.open_after_close` was keyed by `signal_id` and owned by `signal_owner`; it opened for the strategy author's delivery (`DeliveryPort.of_signal_author`). There was no two-subscriber reverse test. C.8 keys it by the delivery and adds the test.
      - `execution.settle` and `attempt_owner` still resolve through `signal_id`/the attempt's own `user_id`, as before. (C.8 verified both: see its note.)
    - **Proof by mutation (each seen red on an assertion, then reverted):**
      - `AllocateCapital`: the resume lookup, the lock key, `is_disabled`, the balance read, `sum_active` and the insert each given the author instead of the command's user (`test_allocate_capital.py`, 4 tests); `delivery_id` not passed to the reservation (`test_allocate_capital_integration.py`).
      - `ProcessDelivery`: the trade capability, the holding guard, the balance refresh, the sizing read, the share source (`policy.allocation_percent`), `AllocateCommand.user_id` and `.delivery_id`, `PlaceCommand.user_id`, `latest_close_for` and `CloseCommand.user_id` each switched back to the author (`test_process_delivery.py`); the missing-halves refusal defaulted to `open`, and the unparseable-string path defaulted, and the ERROR log lowered to WARNING.
      - `SignalContextAdapter`: `own_reservation` read as the author; the prior lookup called with the author's user. The second needed a stronger test: the delivery user and the strategy author were the same id in it, so it now authors the strategy as another user.
      - `latest_before`: the subscription filter (needed the new `test_a_resubscription_does_not_inherit_the_reservation_of_its_ended_predecessor`, since the user filter alone hid it), the user filter, the symbol filter, the spelling set narrowed to the alert's own, `<` widened to `<=`, and the ordering reversed.
      - `delivery_owner` returning the strategy author; the `delivery.process` and `signal.process` handlers swapped in the handler table.
      - `SettleExecution`: the `end_if_flat` call removed; the pool lock removed. `EndLeavingSubscription`: the holding check removed; the LEAVING-only guard removed.
      - `SqlAlchemyFailedJobSignalReader`: the `delivery.process` case removed.
      - The share preview: the subscription default removed; the lookup keyed by the strategy's author (needed the new `test_the_authors_subscription_is_not_the_callers_default_share_either`, since the author and the caller were the same user in the other tests).
      - Migration 0032: `nullable=False` removed; the `signal_id` unique drop removed; the downgrade's restore removed.
    - **Not mutation-proved:**
      - the `ReservationRow.strategy_id` filter of `latest_before`: with the subscription filter it is redundant (a subscription belongs to one strategy), and no valid row can show it;
      - the `_EFFECTS_NEEDED` mismatch check of `ProcessDelivery` beyond the unrecognised-string path;
      - the order of the pool lock before the row lock in `SettleExecution` beyond the unit test that asserts the call order;
      - the `of_signal_author` read the continuation uses (removed by C.8);
      - the raise in `_signal_unique_name` when no unique is found.
    - **Existing tests changed at the helper level, and why (none weakened, none dropped, no `skip`/`xfail`):**
      - `tests/owner.py` gained `ensure_author_subscription` (the author's ACTIVE subscription, at the strategy's own share, as `RegisterStrategy` makes it) and `ensure_delivery` gained `subscription_strategy_id`. A strategy seeded raw has no subscriber, so `FanOutSignal` would deliver to nobody.
      - `test_no_fee_rate_pool_refused.py` (`seed_strategy_on` seeds the author's subscription; a signal now takes two `run_once` calls, fan-out then delivery) and `test_simulated_fill_webhook_to_ledger.py` (the share it sets is the subscription's) share those helpers; `test_simulated_price_refusals_integration.py` and `test_settle_outcomes_integration.py` build `SettleExecution` with the pool lock and the leaving port.
      - `test_booking_proposal_repository_integration.py`, `test_archive_strategy_integration.py`, `test_delete_strategy_integration.py` and `test_history_adapter_integration.py` seeded reservations without `delivery_id`, now NOT NULL; they seed the delivery too (the history test hosts its subscription on a throwaway strategy so no count under test sees it).
      - `test_archive_vs_allocate_concurrency.py`, `test_delete_credential_integration.py` and `test_allocate_pool_disabled_integration.py` build `AllocateCommand` through `allocate_command`, which seeds its delivery first.
      - `test_signal_context.py`: the three tests moved to `load(delivery)`. The one that read the author's reservation now reads the delivery user's (the same behaviour, scoped by user); a test for the prior lookup was added.
      - `test_main_trade_capability_wiring.py` follows the builder's new name `_build_process_delivery`.
      - `test_delivery_flow_integration.py` and `test_pre_upgrade_position_integration.py` (written in the cut session, never green): the fake venue reports a fill under the alert's `.P` spelling and sizes at the alert's price, so the held quantities are 500 and 100, not 250 and 50, and the ledger is read under both spellings; the pre-upgrade signals are both spelled `STXUSDT.P`, since `find_prior` classifies over one exact spelling, and a processed signal carries `decided_at`.
- [x] C.7 Outcomes per delivery (finding d). `SqlAlchemySignalOutcomeRepository` writes `signal_deliveries` and locks the delivery row, not the signal's. Every writer the map listed moves with it: `process_signal`, `skip_recorder`, `place_order`, `close_position`, `settle_execution`, `open_after_close` and `exhausted_job_recorder`.
  - A test proves that two deliveries of one signal record their outcomes independently.
  - The signals' own outcome columns are no longer written.
  - After a fan-out that delivered, the signal itself stays `ACCEPTED` (C.5 settles it only when nothing was delivered). Every reader of a signal's status (the panel's signal list, the alerts, `failed_job_signal_reader`) must read its deliveries' outcomes instead, so no signal reads as pending forever.
  - Done on 2026-10-28, not ticked.
    - **Decisions applied (the parent's, recorded here):**
      1. **Strategy-level refusals stay on the signal row.** `FanOutSignal` settles a signal `REJECTED` when no delivery exists (archived strategy, `NO_POSITION_TO_CLOSE`, `NO_ACTIVE_SUBSCRIPTION`), and an exhausted `signal.process` ends the signal the same way. There is no delivery to hold either, and decision 27 forbids a signal staying `ACCEPTED` with no trace. "The signals' own outcome columns are no longer written" is therefore read as "no longer written by any delivery-level writer". The "Deploy shape" paragraph and the PR D line now say the four signal columns stay; only `strategies.allocation_percent` is still dropped.
      2. **Finding the delivery of an execution: pulled forward from C.8.** `execution_attempts.delivery_id` is written now, beside `signal_id`, by `PlaceOrder` (from the new `PlaceCommand.delivery_id`) and `ClosePosition` (from the new `CloseCommand.delivery_id`, `None` for an orphan close, like `signal_id`). A closing attempt has no reservation, and the reservation a close unwinds names the OPENING delivery, so the command is its only route. For an open, the reservation could not be used either: `ReservationSnapshot` is built by `allocation/infrastructure/reservation_gateway.py`, outside C.7's edit surface. Settle and the exhausted-job reader read `attempt.delivery_id` for an open and a close alike; the 0032 backfill gave every existing attempt one. A NULL link (orphan close, attempt with no delivery) records nothing, as a NULL `signal_id` did. `execution/domain/execution_attempt.py` gained the field (outside the listed surface, one line; flagged to the parent). C.8 still owns `execution.settle`/`attempt_owner` resolution, `CloseOrphans`, `signal.open_after_close` keyed by delivery, the pricing source and the history count.
      3. **`open_after_close`** stays keyed by `signal_id`; an abandonment resolves the author's delivery through `SqlAlchemyDeliveries.author_delivery_id` (`of_signal_author`) and ends that delivery. A signal with no author delivery raises: loud.
      4. **Exhausted jobs.** `SqlAlchemyFailedJobSignalReader.target_for` returns a `FailedJobTarget`: the signal for `signal.process` (fan-out), the delivery for `delivery.process` (missing is loud), the author's delivery for `signal.open_after_close`, and the attempt's own delivery for `execution.settle` (`None` records nothing). `ExhaustedJobSignalRecorder` takes both outcome ports and logs which one it ended.
    - **What changed:**
      - `DeliveryOutcomePort` and `SqlAlchemyDeliveryOutcomeAdapter` (`signals/application/ports.py`, `signals/infrastructure/outcome_repository.py`): the terminal latch of `SqlAlchemySignalOutcomeAdapter` unchanged (`record`, `record_unless_terminal`, the fresh `populate_existing` read, `FOR UPDATE`, identical repeat silent, a conflict one WARNING), on the DELIVERY's row. The WARNING names the delivery and the signal. `SignalOutcomePort` and its adapter are untouched, and now serve only the strategy-level refusals.
      - Writers moved to the delivery: `ProcessDelivery` (every `_reject`, the two `PROCESSING` writes, `REVERSE_NEW_SIDE_UNHOLDABLE`; its private methods take the `Delivery` instead of a signal id), `SignalSkipRecorder` (`AllocateCapital` passes `command.delivery_id`), `SignalOrderOutcomeRecorder` (`PlaceOrder`, `ClosePosition`), `SignalSettleOutcomeRecorder` (`record_close_filled` takes the delivery and the signal, since "is this a REVERSE" is a question about the signal), `OpenAfterClose`, `ExhaustedJobSignalRecorder`. Wiring in `main.py` follows (`delivery_outcomes`).
      - Logs: every refusal WARNING still names the signal and its text is still the stored detail. `_reject` adds one INFO line naming the delivery and the signal, `OpenAfterClose._abandon` one INFO line naming both, the exhausted recorder one INFO line naming the job and what it ended.
    - **Readers of a signal's status, with evidence:** none outside the outcome adapters exist. Searched `backend/src` for `SignalRow`, `signals.status`, `outcome_reason`, `outcome_detail`, `decided_at` and `SignalStatus`: the matches are the signals repository (`repository.py:49` builds `WebhookSignal.status`, which nothing reads), `rehearsal_pricing_source.py` (reads `SignalRow.price`), `execution/infrastructure/repository.py:323` (counts a strategy's signals), `job_owner.py`, `fan_out_adapters.py`, `delivery_adapters.py` (joins only) and the two outcome writers. No API route returns a signal, `frontend/src` has no signal list (its `decided_at`/`PROCESSED` matches are the discrepancy bookings), and the alert channel reads logs, not rows. The panel's signal list and any alert on a signal's status do not exist, so none was built. The one reader that did exist, `failed_job_signal_reader`, now maps jobs to deliveries (above). Two `allocate_capital.py` comments that said `signals.status never leaves ACCEPTED` now say the delivery's. A signal-list reader built later must read `signal_deliveries` for any signal that was delivered.
    - **Tests (strict TDD, with an honest exception):** this unit was written code first, so no new test was seen RED before its code; the proof is by mutation, below. New files and tests: `test_delivery_outcome_repository.py` (9 tests on PostgreSQL: two deliveries of one signal record independent outcomes with no warning and the signal row left `ACCEPTED` with null columns; the latch per delivery; an identical repeat silent; `record_unless_terminal` silent; unknown delivery loud; rollback discards; a write on the second delivery does not wait for a holder of the first, and a second writer on the same delivery does wait, `not task.done()`; the signal adapter still writes only the signal's row), `test_exhausted_jobs_integration.py` (fan-out ends the signal row, every delivery kind ends the delivery, two deliveries of one signal exhaust independently, the delivery-row lock-hold), `test_process_delivery.py` (commands carry the delivery, a refusal and the orphan `PROCESSING` land on the delivery id, which differs from the signal id), `test_open_after_close_outcomes.py` (the abandonment ends the delivery, not the signal), `test_place_order.py` and `test_close_position.py` (the attempt carries the delivery beside the signal), `test_delivery_flow_integration.py` (each delivery `PROCESSED` on its own row, the stranger's `NO_POSITION_TO_CLOSE` independent of the holders', the signal still `ACCEPTED`). The fan-out refusals writing the signal row were already pinned in `test_fan_out_integration.py`.
    - **Proof by mutation (each seen red on an assertion, then reverted):** `FOR UPDATE` removed from the delivery read (the two lock-hold tests); the terminal latch disabled (seven tests across the adapter and the exhausted-job files); `_reject` recording the signal id (`test_a_refusal_ends_the_delivery_never_the_signal` and the halves test); settle ending `reservation.signal_id` for an open (unit and integration); `PlaceOrder` writing a NULL `delivery_id` (`test_the_opening_attempt_is_linked_to_the_delivery_of_its_command`, the settle integration and the two-subscriber flow).
    - **Not mutation-proved:** the `ClosePosition` command delivery (the unit and integration tests that read it pass on the code, none mutated); the `target_for` branches of `FailedJobTarget` for `signal.open_after_close` and `execution.settle` beyond the integration tests that exercise them; the two new INFO lines; `SqlAlchemyDeliveries.author_delivery_id`.
    - **Existing tests changed, and why (none weakened, none dropped, no `skip`/`xfail`):** the writers' ports now take a delivery, so the fakes and the assertions on WHICH id a writer was handed moved from the signal's to the delivery's. `tests/signals/fakes.py` (the outcome fake serves both ports; `SoleSubscriberAuthorDelivery`), `tests/execution/fakes.py` (delivery ids; `close_filled_signals`), `tests/owner.py` (`ensure_delivery(delivery_id=...)`), `tests/signals/infrastructure/conftest.py` (`seed_execution_attempt(delivery_id=...)`); `test_place_order.py`, `test_close_position.py`, `test_settle_execution.py` (`PlaceCommand`/`CloseCommand`/attempt carry `delivery_id`; outcome assertions on it); `test_allocate_capital_skip_outcomes.py`, `test_allocate_capital_pool_disabled.py` (the skip lands on `command.delivery_id`); `test_open_after_close.py`, `test_open_after_close_integration.py`, `test_open_after_close_outcomes.py` (the new `deliveries` argument); `test_exhausted_job_recorder.py`, `test_failed_job_signal_reader.py` (rewritten for `target_for` and `FailedJobTarget`, same cases plus the new ones; the old "names its signal" cases became "names its delivery" except the fan-out), `test_exhausted_jobs_integration.py` (a delivery row asserted where a signal row was, and "two exhausted jobs of ONE signal" became "of ONE delivery", since a `signal.process` and a settle no longer share a row); `test_settle_outcome_recorder.py`, `test_settle_outcomes_integration.py`, `test_order_outcomes_integration.py`, `test_refusal_outcomes_integration.py`, `test_continuation_outcomes_integration.py`, `test_no_fee_rate_pool_refused.py`, `test_simulated_price_refusals_integration.py`, `test_simulated_fill_webhook_to_ledger.py` (the row read for an outcome is the signal's sole delivery row; their seeds create the delivery and attempts carry it; `test_a_legacy_open_attempt_with_no_link_still_resolves_through_its_reservation` became `..._with_only_its_delivery_link_still_ends_its_delivery`, because 0032 gives a pre-0025 attempt its delivery and settle no longer reads the reservation for it); `test_delivery_flow_integration.py` (the C.6 gap closed: it now asserts each delivery's outcome). Found by the full gate, outside the writer's focused paths: `tests/accounts/application/test_allocate_pool_disabled_integration.py` (two tests; the skip lands on the command's delivery, and the test now also asserts that id differs from the signal's).
    - `SkipRecorderPort.record_skip` (`allocation/application/ports.py`) names its first parameter `delivery_id`, and its docstring names `DeliveryOutcomePort`.
    - Full gate: `ruff=0 mypy=0`, pytest with 2 failures (the `accounts` tests above), fixed and rerun green with `tests/accounts`.
    - **Interim gaps left:**
      - `signal.open_after_close` is still keyed by the signal and opens for the author's delivery, so a non-author subscriber's REVERSE continuation resolves the author's delivery (closed by C.8).
      - `ReservationSnapshot` still carries no `delivery_id`; nothing needs it now.
- [x] C.8 Every job and reader that reaches one execution through `signal_id` takes `delivery_id` instead (finding g):
  - `signal.open_after_close` carries `delivery_id`, with `dedupe_key` `signal.open_after_close:{delivery_id}:{poll}`;
  - `place_order` and `close_position` write `execution_attempts.delivery_id`, and keep writing `signal_id` beside it: the strategy history counts attempts through the signal (see C.2);
  - `execution.settle` and `attempt_owner` resolve through it;
  - `CloseOrphans` seeds by delivery;
  - `failed_job_signal_reader` maps a failed job to its delivery;
  - `rehearsal_pricing_source` reaches the signal's price through the delivery.
  - The history count that blocks delete keeps counting signals.
  - `reservations.signal_id` is still written, for reads only.
  - Done on 2026-10-28, not ticked.
    - **Bullets C.7 had already met, and the test that pins each:** `place_order` and `close_position` write `execution_attempts.delivery_id` beside `signal_id` (`test_place_order.py::test_the_opening_attempt_is_linked_to_the_delivery_of_its_command` and `..._to_the_signal_of_its_reservation`; `test_close_position.py::test_the_closing_attempt_is_linked_to_the_closing_delivery` and `..._to_the_closing_signal`; the flow tests assert `attempt.delivery_id`). `execution.settle` records on `attempt.delivery_id` (`test_settle_execution.py`, `test_settle_outcomes_integration.py`). `failed_job_signal_reader` maps `delivery.process` and `execution.settle` to their delivery (`test_failed_job_signal_reader.py`, `test_a_settle_job_for_a_close_names_the_closing_delivery_not_the_opening_one`). The history count that blocks delete keeps counting signals, untouched. `reservations.signal_id` is still written (`AllocateCommand.signal_id`), untouched.
    - **What changed:**
      1. **The continuation is keyed by the delivery.** `OpenAfterClose.seed(delivery_id, ...)` writes the payload `{delivery_id, awaited_allocation_ids, poll}` (no `signal_id`) and the `dedupe_key` `signal.open_after_close:{delivery_id}:{poll}`. `poll` reads the signal through the new `DeliverySignalPort.signal_of(delivery_id)` (`SqlAlchemyDeliveries.signal_of`), calls `open_now(delivery_id, poll)` and abandons the delivery the job names. A delivery that is gone logs one ERROR naming it and returns without raising. `ProcessDelivery.open_now(delivery_id, poll)` loads that delivery, so the open runs in its user's pool, at its subscription's share. `DeliveryPort.of_signal_author`, `SqlAlchemyDeliveries.of_signal_author` and `author_delivery_id` are removed.
      2. **The seeders take the delivery.** `ContinuationSeederPort.seed` and `CloseOrphans.close` / `CloseOrphansPort.close` take `delivery_id`; `ProcessDelivery` passes `delivery.delivery_id` at all four seed sites and at the orphan close.
      3. **Owner of the continuation.** `handle_signal_open_after_close` resolves the delivery with `job_owner.continuation_delivery_id` and builds its client with `delivery_owner`, the delivery's user. `signal_owner` has no caller left in `src`; it stays, with its test, for the parent to decide.
      4. **Exhausted continuation.** `SqlAlchemyFailedJobSignalReader` resolves `signal.open_after_close` through the same function and checks the delivery exists; a payload that names no single delivery raises `InvariantViolation`. `_author_delivery` is removed.
      5. **Pricing.** `SqlAlchemyRehearsalPricingSource` reaches `SignalRow` through `reservations.delivery_id` and `signal_deliveries.signal_id`. Still one statement.
      6. **`attempt_owner` is unchanged on purpose.** An attempt's `user_id` is the delivery's user by construction (`PlaceCommand.user_id` and `CloseCommand.user_id` are `delivery.user_id`, `process_signal.py` `_handle_consumes`/`_handle_releases`), and an orphan close carries NO delivery yet still has an owner, so resolving through `delivery_id` would lose it. A new test pins a subscriber's open, close and orphan close as the subscriber's.
    - **Legacy payload decision (a job queued before C.8 carries `signal_id` and no `delivery_id`):** `continuation_delivery_id` resolves it to the signal's ONLY delivery, whoever it is for (not "the author's"), and refuses when the signal has none or several (`UnresolvableContinuation`). The handler then logs one ERROR naming the job and the reason, builds no client, polls nothing, and ends the job; retrying cannot change the count, so it does not raise into the backoff. The failed-job reader raises `InvariantViolation` for the same payload. When it resolves, the handler hands `poll` a job whose payload names the delivery, so the next poll is seeded by delivery. Evidence: production at planning held no pending signal job (`jobs` had only `DONE`/`FAILED` signal rows, line 350) and one subscriber per strategy (the author), so every signal has exactly one delivery (0032's backfill) and the sole-delivery rule reproduces the old behaviour exactly; the deploy stops the worker (Deploy shape), so no new fan-out can add a second delivery to a signal whose continuation is still queued under the old key. A refusal needs two deliveries of one signal AND an old-format job, which cannot both exist in production at the deploy.
    - **RED (observed on an assertion before the code unless stated):**
      - `test_a_reverse_closes_and_then_opens_for_each_subscriber_in_their_own_pool` (two subscribers, one `run` per job, on PostgreSQL): `assert {job.dedupe_key ...} == {f"signal.open_after_close:{delivery_id}:0" ...}` failed because one signal-keyed job existed for the two deliveries (the second seed collided).
      - `test_seed_enqueues_the_expected_payload_and_dedupe_key`: payload `{'signal_id': ...} != {'delivery_id': ...}`.
      - `test_a_seeded_continuation_polls_the_signal_of_its_delivery`: `signals.asked == [signal.id]` failed (it asked for the delivery's id).
      - `test_a_continuation_whose_delivery_is_gone_is_abandoned_loudly[owner]`: `len(errors) == 1` failed (0 errors); `[no-owner]` failed on the `assert user_id is not None` of the old code, the same path.
      - `test_the_alert_price_is_reached_through_the_reservations_delivery`: `Decimal('9') != Decimal('0.5')` (the decoy on `reservations.signal_id`).
      - `test_a_continuation_queued_before_c8_resolves_to_its_signals_only_delivery` and `..._for_a_signal_with_two_deliveries_is_refused` (`test_main_job_owner_keys.py`): `['OWNER-BYBIT-KEY-1111'] == ['OTHER-BYBIT-KEY-2222']` and `== []` (the author's key was opened).
      - Against skeletons that returned `UUID(int=0)`: all of `test_continuation_delivery.py` failed on assertions or `DID NOT RAISE`, except `test_an_exhausted_continuation_ends_the_delivery_it_was_seeded_for`, which failed on `InvariantViolation: ... carries no signal_id` from the old reader.
      - **Not seen RED, honestly:** `test_an_abandonment_ends_the_delivery_the_job_names_not_the_signal` failed on an `AttributeError` (the old port), not an assertion; `test_two_deliveries_of_one_signal_seed_two_continuations_that_never_collide` passed at once (old `seed` took any id); and the `ProcessDelivery` edits (`test_process_delivery.py`, 5 new tests and the seeded-id expectation) were written after the code, so they are proved by mutation below.
    - **Mutations (each seen red on an assertion, then reverted and the file diffed to its backup):**
      - `ProcessDelivery`: the deferral seed, the replay seed, the release seed and the orphan close each given `signal_id`, and `open_now` loading another id (6 tests in `test_process_delivery.py`).
      - `OpenAfterClose`: the `dedupe_key` without the delivery; `open_now(signal_id, ...)`; the abandonment recorded on `signal_id`; the unknown-delivery ERROR removed (7 tests across `test_open_after_close.py` and `_outcomes.py`).
      - `continuation_delivery_id`: the legacy branch taking the first of several; the `delivery_id` branch removed (6 tests across `test_continuation_delivery.py` and `test_main_job_owner_keys.py`).
      - `attempt_owner` routed through an inner join on the delivery (the new subscriber test, `test_an_opening_and_a_closing_attempt_belong_to_their_strategys_author` and the settle handler test in `test_main_job_owner_keys.py`).
      - The handler without the normalised payload (the legacy test) and without its ERROR log (the two-deliveries test).
      - The reader without `_existing_delivery`.
      - `CloseOrphans` seeding with another id (2 tests in `test_close_orphans.py`).
    - **Not mutation-proved:** `SqlAlchemyDeliveries.signal_of`'s `UnknownDeliveryError` branch (the unit tests use a fake; the PostgreSQL test `test_an_unknown_delivery_has_no_signal` was not mutated); the poll's own "signal no longer exists" branch (unreachable through the FK, kept as it was); the new docstrings.
    - **Existing tests changed, and why (none weakened, none dropped, no `skip`/`xfail`):**
      - `tests/signals/fakes.py`: `SoleSubscriberAuthorDelivery` became `SoleSubscriberDeliverySignals` (`signal_of(d) -> d`) for the new port; `tests/signals/application/delivery_support.py` and `test_process_delivery.py` lost the `of_signal_author` stub.
      - `test_process_signal.py` (`SpyContinuationSeeder`, `SpyCloseOrphans`), `test_process_signal_deferral_outcomes.py` and `test_open_now_concurrent_redelivery.py` (their seeder and orphan fakes): the first parameter is `delivery_id`, since the ports renamed it. `test_open_now_concurrent_redelivery.py` also seeds and passes the delivery id to `open_now`, and `_setup` returns it.
      - `test_open_after_close.py`: `_job` writes `delivery_id`; `FakeSignalLookupPort` records the ids it is asked for; the seed test expects the delivery payload and key; the one-signal rigs use the new fake. `test_open_after_close_outcomes.py`: `test_an_abandonment_ends_the_authors_delivery_not_the_signal` became `..._ends_the_delivery_the_job_names_not_the_signal`, and seeds then polls. Same assertions on the outcome, and the INFO line naming both ids.
      - `test_open_after_close_integration.py`: the hand-seeded job carries the delivery id (and its `dedupe_key`), and `_open_now` forwards it. `test_continuation_outcomes_integration.py`: the scenario carries the reverse delivery and the job names it; the deleted-signal test now deletes the delivery (the FK forbids deleting a signal that has one).
      - `test_exhausted_jobs_integration.py`: the `signal.open_after_close` case names the delivery. The legacy `signal_id` payload stays pinned by `test_failed_job_signal_reader.py`'s untouched continuation tests.
      - `test_process_delivery.py::test_a_reverse_delivered_as_both_closes_and_seeds_the_open` expects the seed for `DELIVERY` where it expected `SIGNAL`.
    - **Interim gaps left:**
      - `signal_owner` is dead code now (kept with its test, because deleting a test was not allowed).
      - `reservations.signal_id` is written but only the pricing source and the history count read it; a later unit may drop the pricing source's use of it entirely.
      - The continuation's chain survives a deploy only for single-delivery signals (legacy rule above); a multi-delivery legacy job is refused and its subscribers' opens are not placed.
    - Full gate (parent, 2026-10-28): `ruff=0 mypy=0 pytest=0 failing=0`.
- [x] C.9 Archive and delete against every subscriber (finding e, decision 5).
  - Archive takes the pool advisory lock of every pool that holds a non-ENDED subscription of the strategy, in ascending `pool_id` order so two callers cannot deadlock, and only then the row locks (working agreement). It refuses while any subscriber holds an open allocation, and ends every subscription in the same transaction.
  - Delete takes the same locks.
  - The lock-hold harness on real PostgreSQL proves that an opening delivery in a subscriber's pool waits for archive (`not task.done()`) and is then refused as archived. The template is `tests/allocation/infrastructure/test_pool_lock_per_user.py`.
  - Done on 2026-10-28, not ticked.
    - **Decisions applied, with evidence:**
      1. **The set of pools** is every pool named by an ACTIVE or LEAVING subscription of the strategy, joined to `capital_pools` on `(pool_id, user_id)`, deduplicated by `pool_id` and sorted ascending in the APPLICATION (`SubscriberLocks`), so the order does not depend on the adapter. Each lock is derived from the pool's OWN row (exchange, venue, currency, owner), through the unchanged `PoolLockAdapter` and `LockKey`, never from the strategy's market.
      2. **A subscriber whose pool row is gone cannot exist.** `fk_subscriptions_pool` is `(pool_id, user_id) -> capital_pools (id, user_id)` with no `ON DELETE` (`subscriptions/infrastructure/models.py:51`), so the database refuses to delete a pool a subscription names, in any status. The join is therefore inner and cannot lose a row; no branch for the impossible case was written, because it could not be tested and a guess there would hide a schema change.
      3. **A subscriber who joins between the read and the locks is refused, not locked late.** Locking the new pool after the others would break the ascending order. `SubscriberLocks.confirm` re-reads the set UNDER the strategy row lock and raises `SubscribersChanged` (409 `SUBSCRIBERS_CHANGED`, session rolled back, one WARNING naming the strategy and the pool ids) when it holds a pool the first read did not lock; nothing has been written by then, and trying again reads the larger set. Why the re-read is complete: `subscriptions.strategy_id` is a foreign key, so an INSERT in flight holds `FOR KEY SHARE` on the strategy row, which the archive's `FOR UPDATE` conflicts with. An insert in flight makes the row lock wait until it commits and the re-read then sees it (`test_a_subscription_being_inserted_makes_the_row_lock_wait_and_is_then_seen`, which would be red if the claim were false); one that arrives later waits for the archive. A subscriber who LEFT in between only leaves an unneeded lock held, harmless (`test_a_subscriber_who_left_after_the_first_read_does_not_refuse`).
      4. **"Holds an open allocation"** is read as before: `StrategyExposureAdapter` already asked EVERY user's ledger holdings (every spelling, per allocation), live reservations and submitted attempts, so a non-author holder always refused. What changed is WHO is named: `StrategySubscribersAdapter.holders` asks the subscriptions module's own `OpenAllocationAdapter` for each ACTIVE or LEAVING subscriber, and the refusal and its new WARNING carry `held_by=['author', 'user 1a2b3c4d']` (author, or the first eight characters of the id; never an e-mail, never the full id). The reason, the HTTP mapping and the 409 body are unchanged. Exposure no live subscriber holds (an in-flight attempt, an ended subscription) still refuses with `held_by=[]`.
      5. **Archive ends every live subscription** through `Subscription.end` (`StrategySubscribersAdapter.end_all`, rows locked `FOR UPDATE`), after `archived_at` is written and before the one commit, and logs one INFO line `subscriptions_ended=N` after it. An ENDED subscription is left as it was.
      6. **A replay of an archive also ends what is still live** (one INFO line only when it ended something), keeping the original `archived_at`. Reason: a strategy archived before this unit still has its author ACTIVE, and `Subscribe` can still insert one after an archive (below); a replay heals both. Not in the spec; one line to drop if unwanted.
      7. **Delete** takes the same locks in the same order and re-reads under the row lock; the cascade of decision 19 is the database's (`fk_subscriptions_strategy`), counted by the existing INFO line.
    - **What changed:** new `strategies/application/subscriber_locks.py` (`SubscriberLocks`, `SubscribersChanged`), `StrategySubscribersPort` and `SubscriberPool` in `strategies/application/ports.py`, `strategies/infrastructure/subscribers_adapter.py`, `SqlAlchemySubscriptionRepository.live_for_strategy_for_update` (global by design, like the exposure reads), `ArchiveStrategy` and `DeleteStrategy` (new required `subscribers` argument), the router's wiring and 409 mapping. `PoolLockPort`, `PoolLockAdapter`, `LockKey` and `advisory_lock.py` are untouched; `main.py` needed no change. Disable is untouched.
    - **RED observed on an assertion, before the code (against skeletons that kept the old behaviour):** `test_subscriber_locks.py`: `test_archive_locks_every_subscribers_pool_in_ascending_pool_id_order` and the delete twin (`[OWNER] == [USER_B, OWNER, USER_C]`), `test_a_pool_listed_twice_is_locked_once`, `test_the_lock_is_the_pools_own_market_not_the_strategys`, `test_every_pool_lock_comes_before_the_row_lock_and_the_set_is_read_before_both` and its delete twin (event lists differ), `test_a_strategy_nobody_subscribes_to_takes_no_pool_lock_and_still_archives` (`[lock] == []`), the three `SubscribersChanged` tests (`DID NOT RAISE`), `test_a_non_author_holder_refuses_and_is_named_by_id_prefix_only` (`'bbbbbbbb' in message`), `test_the_authors_holding_keeps_the_existing_refusal` (`'author' in message`), `test_the_holders_are_asked_of_the_subscribers_read_under_the_locks` (`[] == [[...]]`), `test_archiving_ends_every_subscription_in_the_archive_transaction` and the replay test (`[] == [NOW]`). The PostgreSQL tests were written after the code; their old-behaviour RED is the mutation below.
    - **Proof by mutation (each seen red on an assertion, then reverted):** `live_pools` cut to its first row, which is what locking the author's pool alone does (`test_an_opening_in_a_subscribers_pool_waits_for_archive_and_is_then_refused_as_archived`, `test_a_delivery_in_a_subscribers_pool_waits_for_delete`, `test_the_locks_are_taken_lowest_pool_first_and_the_highest_is_waited_on_last`, `test_two_archivers_of_strategies_sharing_pools_do_not_deadlock`, both re-read tests: all `not task.done()` or `DID NOT RAISE`); the sort reversed (the lowest-first lock-hold test and three unit tests); the dedupe removed (`test_a_pool_listed_twice_is_locked_once`); `confirm` never raising (five tests, unit and PostgreSQL); `confirm` refusing when the set shrinks (`test_a_subscriber_who_left_after_the_first_read_does_not_refuse`); `end_all` skipped on archive and on replay (four tests); the holder shown by its full id (seven tests); `_holder_names` indexing its first entry (`test_a_refusal_for_exposure_nobody_holds_still_refuses`); `ondelete="CASCADE"` removed from `fk_subscriptions_strategy` in the model (`test_delete_takes_the_subscriptions_of_several_users_with_it`, which passes on the old code since the cascade was already the database's); the two router branches removed (`test_subscribers_changed_mapping.py`, red on the uncaught `SubscribersChanged`).
    - **Not mutation-proved:** the ascending-order proof in `test_two_archivers_of_strategies_sharing_pools_do_not_deadlock` (both archivers sort the same way, so reversing both still passes; the ordering itself is pinned by the other lock-hold test and the unit tests); the replay INFO line wording; `StrategySubscribersAdapter.holders` beyond the refusal tests that exercise it; the archive WARNING's exact text.
    - **Existing tests changed, and why (none weakened, none dropped, no `skip`/`xfail`):** every construction of `ArchiveStrategy` and `DeleteStrategy` gained the new `subscribers=` argument (a real adapter through the new `tests/strategies/wiring.py`, a fake in `test_delete_strategy.py`, `None` in the unknown-id archive test): `test_archive_strategy_integration.py` (2 sites), `test_archive_vs_allocate_concurrency.py`, `test_delete_strategy_integration.py`, `test_delete_strategy_concurrency.py` (2 sites), `test_router.py` (the miscounting override), `test_delete_strategy.py` (a fake returning the author's pool, silent in the event log so every ordering assertion is unchanged). `_seed_strategy` in `test_archive_vs_allocate_concurrency.py` and `test_delete_strategy_concurrency.py` now also seeds the author's subscription (what `RegisterStrategy` makes): without it the strategy has no subscriber, so the archive or delete locks no pool and five lock-wait assertions went red on the new code; the assertions are as they were.
    - **Interim gaps left (for the parent):**
      - **`Subscribe` does not lock the strategy and does not re-check `archived` under a lock** (`subscriptions/application/subscribe.py:44-48` reads it unlocked). An insert that lands after an archive's row lock waits for it, then succeeds: an ACTIVE subscription to an archived strategy. Harmless to money (`FanOutSignal` refuses an archived strategy) and healed by a replayed archive, but a later unit could lock the strategy row `FOR SHARE` in `Subscribe`.
      - A refused archive or delete (`SUBSCRIBERS_CHANGED`) has no retry on the server; the caller asks again.
      - The `held_by` list is computed from ACTIVE and LEAVING subscribers only; ledger or reservation rows of a user with no live subscription still refuse (the exposure read is global) but are not named.
    - The archive replay that ends leftover live subscriptions was not asked for; the parent kept it (one isolated block, it heals strategies archived before C.9 and the `Subscribe` race above).
    - Full gate (parent, 2026-10-28): `ruff=0 mypy=0 pytest=0 failing=0`.
- [x] C.10 The delete-key exposure (`accounts/infrastructure/pool_exposure_adapter.py:71-80`) reads the user's non-ENDED subscriptions on that market, instead of the strategies they author. The cross-user test from B.D.1 stays green, and one new test proves that a subscription blocks the delete.
  - Done on 2026-10-28, written inline by the parent. Owner decision 20 narrowed "non-ENDED" to ACTIVE subscriptions to ENABLED strategies: a LEAVING subscription's open position already blocks through the ledger holdings, and a disabled strategy fans out nothing.
  - The read joins `subscriptions` to the user's own pool on the market (`capital_pools` on `(pool_id, user_id)`) and to the strategy. It no longer filters `author_id`, so an author whose own subscription is ENDED is not blocked by their enabled strategy.
  - RED on assertions before the change: `test_a_subscribers_active_subscription_to_an_enabled_strategy_is_exposure` and `test_another_users_active_subscription_is_not_this_users_exposure`. Proved by mutation: `status != 'ENDED'` reddens `test_a_leaving_or_ended_subscription_is_not_exposure`; dropping the enabled filter reddens `test_a_disabled_strategy_is_not_reported_as_enabled` and three more; dropping the exchange and venue filters reddens `test_another_pools_exposure_is_not_this_pools`.
  - The tests that seed an enabled strategy now seed its author's ACTIVE subscription too, as `RegisterStrategy` does: `_strategy` in `test_pool_exposure_adapter.py` and `test_delete_credential_integration.py`, and two router tests.
  - Full gate on 2026-10-28: `ruff=0 mypy=0 pytest=0 failing=0`.
  - Follow-up for the panel (not this task): the 409's `enabled_strategies` copy says "Disable it first", which a subscriber cannot do; their remedy is to leave. Non-admins have no strategy list until PR F.
- [x] C.11 Concurrency on real PostgreSQL, with the lock-hold harness:
  - two deliveries of one signal for two users take two different pool locks, and neither waits for the other;
  - two deliveries for one user's pool serialize.
  - Done on 2026-10-28, written inline by the parent, in `tests/allocation/infrastructure/test_delivery_pool_lock_concurrency.py`. Tests only: the locks were built in B.4 and C.6.
  - The holder is a real `AllocateCapital` run paused at its commit, so the lock it holds is the one the use case took for its delivery. The two-user test runs in both orders (author holds, subscriber holds). The same-user test proves the queue with `not task.done()` plus a NOT-granted `pg_locks` row for that user's pool key.
  - They passed at once, so they were proved by mutation of `allocate_capital.py:181`: locking on `policy.author_id` reddens both two-user cases; removing the lock reddens the same-user test.
  - Full gate on 2026-10-28: the first run failed once on `test_a_reverse_closes_and_then_opens_for_each_subscriber_in_their_own_pool` (C.8), which this task does not touch. It passed alone, after the new file, and three times in its own file; the rerun was `ruff=0 mypy=0 pytest=0 failing=0`. Recorded as an intermittent for the final verifier; the failing line was not captured.

### Frontend

- [x] C.12 The share editor (`features/strategies/PoolShareEditor.tsx`) edits the signed-in user's subscription (`PATCH /api/subscriptions/{id}`), not the strategy.
  - ~~The strategy page shows that subscription's state, with Subscribe and Leave. LEAVING reads as "closes with the strategy's next close".~~ Amended by decision 22: an author cannot leave their own strategy, and in PR C the strategy pages are the admin's, who wrote every strategy. So C.12 has no Subscribe or Leave; they move to PR F. `Leave` refuses the author with 409 `AUTHOR_CANNOT_LEAVE` (backend, red first).
  - `NewStrategyDialog` still sends the share, which now becomes the author's subscription.
  - `types.ts` and `strategies.ts` follow the API.
  - EN and ES copy, with ES in "usted".
  - Each changed behaviour gets its test, red first.
  - Done (2026-10-28), in two commits.
    - **Backend, decision 22.** `StrategyMarket` gained `author_id`. `Leave` refuses the author after the unlocked reads and before the pool lock, and the router maps it to 409 `AUTHOR_CANNOT_LEAVE`. Both new tests were red on assertions first: `test_the_author_cannot_leave_and_nothing_is_locked_or_written` (DID NOT RAISE) and `test_the_author_leaving_their_own_strategy_is_a_409_and_changes_nothing` (200 != 409). Gate green: `ruff=0 mypy=0 pytest=0 failing=0`.
    - **Frontend.**
      - `Strategy` lost `allocation_percent` and gained `subscription: Subscription | null`, and `isStrategy` checks it: a malformed or absent key is an error. Before this, every strategy read on the branch failed, because `isStrategy` still required the share the API no longer sends.
      - The new `shared/api/subscriptions.ts` holds `isSubscription`, `setSubscriptionShare` and `useSetSubscriptionShare`. On success the hook writes the answer into the cached strategy's `subscription`; settled, it invalidates `['strategies']` and `['strategy', id]`, which also refreshes the preview under that key.
      - `setStrategyAllocationPercent`, `useSetAllocationPercent` and `strategies.share.test.ts` are gone.
      - The editor reads the subscription's share. With no subscription it shows `share.none` and no control. A LEAVING subscription reads its share with the control disabled, under `share.leaving`. A 409 `SUBSCRIPTION_NOT_ACTIVE` shows `share.notActive`; the strategy-archived mapping went, since the subscription route never answers it. `share.archived` stays, because `StrategyTitle` uses it.
      - The test harness gained `subscriptionOf`. Fixtures that do not exercise the share carry `subscription: null`.
      - Red first: the new API tests failed on assertions against a skeleton. The editor's tests failed on presence after a structural swap of the hook, because the component still read the old share.
      - Mutations: removing the subscription check from `isStrategy`, removing the status check from `isSubscription`, adding a `['positions','open']` invalidation, making LEAVING editable, and unmapping `SUBSCRIPTION_NOT_ACTIVE` each turned their tests red. All were restored.
      - Gate: `npm run lint` 0, `npm test` 102 files and 2937 tests passed.
    - **C.10's panel follow-up is settled.** With decision 22 the author has no Leave, so "Disable it first" is the right remedy in that 409. A subscriber who is not the author sees no strategy page before PR F, so that copy is revisited there.
    - **For LEAVING.** Archiving refuses an open position, and the author cannot leave, so the author's subscription cannot reach LEAVING in PR C. Its display is defensive, and it serves PR F.

### Independent verification (2026-10-28)

- [x] C.V An independent verifier (Opus) checked C.1-C.12 against this section, `design.md` and decisions 1-22.
  - **Base.** PR C's base is `origin/main` `7f67fc3`: 21 commits. The local `main` is stale, and diffing against it also pulls in PR A and PR B.
  - **Verdict.** C.1-C.4 and C.6-C.12 pass. C.5 had one blocker.
  - **B1, fixed.** A close could be fanned out before the opening's deliveries had run: a backlog does it, such as the worker stopped through a deploy, a restart, or a slow job ahead. The queue claims by `run_after`, and a signal's delivery jobs are enqueued only when that signal fans out.
    - Before the fix, the close's fan-out found no holder. The signal ended `REJECTED` / `NO_POSITION_TO_CLOSE` with an INFO line, and then the opening opened for every subscriber, with nothing left to close it.
    - The fix: `SqlAlchemySubscribers.live_holders` also counts a subscription that has a pending delivery (`ACCEPTED` or `PROCESSING`) of an EARLIER signal of the strategy, on that symbol under any spelling, that leaves a position open (`position_size != 0`). That delivery's job sits ahead of the close's, so the close runs after it. If the opening's fills have not settled, the close raises `NothingRecordedYet` and retries, as before.
    - If the opening is then refused, the close finds no reservation and ends `NO_POSITION_TO_CLOSE` with a WARNING, placing nothing (`process_signal.py:773-787`).
    - Tests, red first on assertions:
      - `test_close_queued_before_open_delivery.py`: the verifier's probe, which held 500 open before the fix. Its `_drain` retries `NothingRecordedYet` the way the worker does.
      - `test_an_earlier_opening_still_waiting_for_its_delivery_makes_a_holder`.
      - `test_another_subscriptions_pending_opening_does_not_make_this_one_a_holder`.
    - Guard tests:
      - `test_a_pending_delivery_makes_no_holder_when`, five cases: the delivery already ran, it was refused, its signal was a close, it was on another symbol, it came after the close.
      - `test_a_close_queued_behind_an_opening_that_is_then_refused_places_nothing`.
    - Mutation proofs: each of the six filters, and the no-reservation early return, turned their tests red. All were restored.
    - Two existing tests change on purpose:
      - `test_a_new_subscriber_gets_the_next_opening_and_so_its_close`. It was "... but not the close", which asserted B1.
      - `test_a_reservation_that_no_longer_holds_capital_does_not_make_a_holder`. Its seed left the filled reservation's delivery ACCEPTED, so it now marks it PROCESSED.
  - **Recheck of B1 (2026-10-29): CLOSED.** A backlogged close closes what its opening opens. The verifier's probe also shows that a backlogged reverse ends with each subscriber short in their own pool. Both changed tests reflect the fix and hide no regression.
  - **B1a, opened by the B1 fix. The owner authorized a second correction on 2026-10-29 ("Dale, autorizo la segunda corrección para B1a").** A close now reaches a subscription whose awaited opening ends up holding nothing. `latest_before` (`delivery_adapters.py:81-109`) returns the subscription's latest reservation on the symbol in any status. After an earlier round trip, that is the old allocation, whose close already FILLED. `_handle_releases` (`process_signal.py:814-829`) takes it as an idempotent retry and returns with no order, no outcome and no log line, so the delivery and its signal stay `ACCEPTED` for ever. No money moves. The baseline refused the same close as `NO_POSITION_TO_CLOSE` with a WARNING.
    - **Two ways in:**
      - A backlog where the opening is then refused.
      - Without a backlog: 0032 copies production's 17 `ACCEPTED` signals into `ACCEPTED` deliveries that have no job. Any of those that is an opening makes its subscription a holder of every later close on that symbol.
    - **The verifier's regression test,** `test_close_to_a_subscriber_who_never_opened.py` (two cases), failed with `('ACCEPTED', None)`. Its content is in the recheck report.
    - **Fix directions:**
      - Count a pending delivery only while its `delivery.process` job is unfinished.
      - In `_handle_releases`, treat an existing non-FAILED close as a replay only when it belongs to this delivery. Otherwise refuse it as `NO_POSITION_TO_CLOSE` with a WARNING.
    - **Fixed, both directions:**
      - `_awaits_opening` joins the delivery's `delivery.process` job (`dedupe_key = 'delivery:<id>'`) and counts it only while that job is `PENDING` or `CLAIMED`. A job that is `DONE` or exhausted (`FAILED`), or no job at all (0032's backfill), makes no holder.
      - `_handle_releases` refuses an existing non-FAILED close that belongs to ANOTHER delivery (`existing_close.delivery_id != delivery.delivery_id`). It ends `NO_POSITION_TO_CLOSE` with one WARNING naming the close attempt, plus "and the new side was not opened" for a reverse. A close of this same delivery is still a silent replay. A FAILED close keeps its existing paths: a plain close retries and a reverse reports the failure.
      - A legacy close placed before PR C carries the `delivery_id` that 0032 backfills (`0032_signal_deliveries.py:178-189`): the close's own signal's delivery, else the delivery of the reservation it closed. That is never a later delivery's, so it never counts as a replay of a later close. (Corrected by the recheck: this line first said a legacy close has no `delivery_id`.)
      - Changed behaviour, beyond B1a: a reverse whose prior allocation another delivery has already closed, or is still closing, is now refused with a WARNING. It used to seed a continuation and open the new side. The recheck shows this is B1b, below.
    - **Tests, red first on assertions:**
      - The verifier's two tests, strengthened. The backlog case must end `REJECTED` / `NO_POSITION_TO_CLOSE` with the WARNING. The backfill case must get no delivery at all, so it stayed red on `('REJECTED', 'NO_POSITION_TO_CLOSE')` until the second direction landed.
      - `test_a_pending_delivery_whose_job_will_never_run_makes_no_holder_when`, three cases: `DONE`, `FAILED`, no job.
      - Proven by mutation: `test_a_pending_delivery_whose_job_is_being_worked_still_makes_a_holder` (counting only `PENDING`), and `test_a_reverse_whose_allocation_another_delivery_closed_is_refused_with_a_warning` (dropping the delivery comparison). Dropping the FAILED exclusion reddens the two existing FAILED-close tests.
      - `_pending_delivery` in `test_fan_out_integration.py` now writes the delivery's live job too, as fan-out does.
      - Eight existing replay tests (five unit, three in `test_replay_outcomes_integration.py`) seeded the earlier close with no `delivery_id`. They describe a retry of the same delivery, so the seed now carries that delivery's id.
    - **Intermittent B1 test, fixed in the same correction.** `_retries_are_due` set `run_after = now()` on the server, but `claim` compares against the Python clock, which can trail it by milliseconds. A job was then not due, and four passes were not enough: 2 of 3 runs failed with an `execution.settle` job left `PENDING`. It now sets `run_after` a minute back, and 5 of 5 runs passed.
  - **Recheck of B1a against `e1314bc` (2026-10-29): CLOSED for both ways in, but the correction causes B1b.**
    - Both ways in now end correctly. The backlog case ends `REJECTED` / `NO_POSITION_TO_CLOSE` with a WARNING. The backfilled delivery makes no holder.
    - The changed tests describe production faithfully. The `concat` join gets a parameterized index lookup on `jobs_dedupe_key_key`.
    - A retry of a delivery's own close is still a silent replay. Only `_handle_releases` places a close that carries a delivery's id.
  - **B1b, caused by B1a's correction. The owner authorized a third correction on 2026-10-29 ("Si").**
    - **What happens:** the strategy is long, then reverses to short (R1), then reverses back to long (R2), and both reverses are queued before the worker reaches them (a deploy or a restart). R1 closes the long allocation. R2's `latest_before` is still that allocation, and its close belongs to R1's delivery, so R2 is refused: "nothing was closed, and the new side was not opened". R2 then supersedes R1's continuation, so every subscriber ends flat while the strategy is long. This happens whether R1's close is `SUBMITTED` or `FILLED`.
    - **The baseline:** at `7f67fc3` and at `0fdeee4`, R2 seeds a continuation, waits for the close, and opens long. The verifier's probe held 500 / 100 at `0fdeee4`, and 0 / 0 at `e1314bc`.
    - **The probe:** `test_two_backlogged_reverses_end_on_the_strategys_side`. It passes at `0fdeee4` and fails at `e1314bc`. Its content is in the recheck report. Its signals sit at minutes 28-29, because a continuation abandons a signal older than 600 s.
    - **Directions:**
      - The verifier's: on the reverse path, keep seed-and-open when the other delivery's signal is the immediately preceding one on the symbol.
      - The parent's, simpler: refuse another delivery's close only on the plain-close path. A reverse keeps the baseline seed-and-open. For a reverse that reaches a subscriber holding nothing, that opens the new side, which is what a non-holder gets anyway, so nothing ends silent.
    - **Fixed with the parent's direction.** `_handle_releases` refuses a non-FAILED close that is not this delivery's only when the delivery does not wire a reverse (`and not is_reverse_wiring`). A wiring reverse seeds its continuation on that close and opens, as at `7f67fc3`. A reverse whose new side is not holdable (a spot short) closes alone, so it is still refused. The WARNING now reads "was already closed by close attempt <id>, which is not this delivery's", which is also true for a close booked by reconciliation.
    - **Tests:**
      - The verifier's probe, `test_two_backlogged_reverses.py`, was red first on `held > 0`.
      - `test_a_reverse_whose_allocation_another_delivery_closed_waits_for_it_and_opens` replaces the B1a unit test that asserted the refusal for a reverse.
      - `test_a_plain_close_whose_allocation_another_delivery_closed_is_refused_with_a_warning` keeps B1a's refusal pinned at unit level.
      - Mutations: dropping `not is_reverse_wiring` reddens the probe and the reverse unit test. Dropping the refusal reddens the plain unit test. Both mutations were restored.
  - **Recheck of B1b against `6adb011` (2026-10-29): CLOSED, and B1a is still closed. No blocker.**
    - Two backlogged reverses end on the strategy's side whether R1's close is still `SUBMITTED` or already `FILLED`.
      - Each subscriber holds exactly one open, and R2 opens once.
      - R1 ends `SIGNAL_SUPERSEDED` and R2 ends `PROCESSED`, with no jobs left.
      - Dropping `not is_reverse_wiring` reddens the verifier's stronger probes.
    - B1a's shape with a reverse (a refused opening, then a reverse) seeds on the old close and opens the new side. If the pool is still empty, it ends `NOTHING_TO_ALLOCATE`, and past 600 s it ends `CONTINUATION_TIMED_OUT`. It is never stuck, and the subscriber ends on the strategy's side, where `7f67fc3` left them flat.
    - A non-holdable reverse (a spot short) is still refused `NO_POSITION_TO_CLOSE` with a WARNING. That ends flat, which is correct.
    - **Advisories, not change-caused:**
      - When a reverse waited on another delivery's close and its open is then refused or times out, the detail says "the close half of this REVERSE already executed". That close was not this delivery's. The wording is cosmetic and the same at `0fdeee4`.
      - The reverse path's FAILED-close and in-flight `open_now` race are identical at `0fdeee4`.
  - **Advisories from the B1a recheck:**
    - A close booked by reconciliation (`approve_booking.py:310-324`, with no delivery id) now makes a later close delivery end `NO_POSITION_TO_CLOSE`, where `7f67fc3` replayed it silently. That is better. The WARNING used to say "closed by another delivery", which is wrong for a booking; B1b's correction rewords it.
  - **The intermittent reverse test: cause found and fixed.** `test_delivery_flow_integration.py` took `_T0 = now() - 30 min` at import. A reverse's open is abandoned once its signal is older than `delayed_open_max_signal_age_seconds` (600 s), so the test failed whenever a full run reached it more than about 9 minutes after collection. `World.t0` is now taken per test, in `_world`. With it pushed 15 minutes back, the test goes red.
  - **Advisories, not reachable in PR C**, because only the owner signs in and decision 22 refuses the author's Leave:
    - **N1, must be closed before PR F.** `Leave` with an opening delivery still queued ends the subscription at once: it counts holdings and live reservations, not queued deliveries. `ProcessDelivery` never reads the subscription's status, so that delivery opens a position no close will reach.
    - **N2.** A subscription made LEAVING only by a live reservation stays LEAVING if that reservation is released unfilled: `end_if_flat` runs only on a closing fill. The partial unique then blocks a new subscription.
    - **N5.** `ProcessDelivery` and `AllocateCapital` do not skip an ENDED subscription. This is the same fix as N1.
    - **New with B1's fix, closed by B1a's.** A delivery left non-terminal for ever made its subscriber a close target for every later close on that symbol. Only a delivery whose job is still live counts now.
  - **Advisories, for the owner or later PRs:**
    - **N3.** An archived strategy has no live subscription, so its page now says "You are not subscribed to this strategy…" where it used to show the share read-only. This applies to the 3 archived "… Test" strategies in production.
    - **N4.** The preview's fallback (`strategies/infrastructure/router.py:617`) and `RegisterStrategy` still use `strategies.allocation_percent`. PR D's 0033 must remove both before dropping the column.
  - **The known advisories, confirmed and unchanged:** single-spelling `find_prior`; the Subscribe-archive race, healed by archive replay; `held_by` empty for holders with no live subscription; no server retry on `SUBSCRIBERS_CHANGED`; `signal_owner` dead code; a multi-delivery legacy continuation refused with an ERROR log.

### Owner-run (production)

- [x] C.0 The read-only pre-check (2026-10-27). Its results are above, under "Production at planning".
- [x] C.13 Before the deploy: a fresh backup, then rehearse 0031 and 0032 on a throwaway restore.
  - Counts unchanged on every existing table.
  - 6 subscriptions: 3 ACTIVE at 30 and 3 ENDED at 5.
  - 48 deliveries, with outcomes equal to their signals'.
  - Every reservation and every attempt has its `delivery_id`.
  - The ledger's `(id, xmin)` unchanged.
  - Downgrade to `0030`, then upgrade again.
  - Every query in the script is run on a local throwaway database at `head` before it is handed over.
  - **Script ready (2026-10-29), `rehearse_0032.sh`, kept in the session scratchpad like the earlier rehearsals.** It needs the merged code on the VPS (it stops with "pull first" otherwise).
    - Preconditions: production at `0030`, exactly one user, both migration files in the checkout, and exactly one author pool per strategy for its market (0031 refuses otherwise). It also lists the live jobs.
    - Steps: backup `/root/sm_pre0031_<UTC>.dump`, restore into `sm_rehearsal_0032`, counts equal to production, `upgrade head`, the head checks, `downgrade 0030`, `upgrade head` again with the same checks, then drop the copy.
    - Head checks:
      - counts and the ledger's `(id, xmin)` unchanged;
      - one author subscription per strategy, at its share, `ACTIVE` unless archived (then `ENDED` at `archived_at`), in a pool of its market;
      - exactly one delivery per signal, with the signal's outcome and `received_at`, for the author's subscription;
      - every reservation and every attempt with its delivery;
      - the new constraints, the live unique index, and the pool-market trigger;
      - the `reservations (signal_id)` unique gone, and `strategies.allocation_percent` nullable.
    - Downgrade checks: the counts, the ledger, every strategy's share restored and `NOT NULL` again, the new tables gone, and the `signal_id` unique back.
    - It prints, without stopping, the deliveries by status and how many `ACCEPTED` deliveries open a position. Those never run, and since `e1314bc` they make no close holder.
    - `jobs` is left out of the count comparison: the live worker enqueues periodic jobs between the dump and the count.
    - **Local run:** a copy of the dev database (4 strategies, 1 archived, 4 signals, 2 reservations, 4 attempts, 6 ledger rows), brought to `0030` with one user, ran the whole script with `REHEARSAL_LOCAL=1`, exit 0. The first local run caught a `GROUP BY` that PostgreSQL refuses. The dev database stayed at `0028`, and the throwaway databases and dumps were removed.
- [x] C.14 Deploy (all checks but the last; see "PR C's delivery"):
  1. pull as `strategy`;
  2. stop `strategy-worker`;
  3. `alembic upgrade head`;
  4. restart both services;
  5. pps.6 for the panel.
  - Check:
    - the panel and every page load;
    - the strategy page shows the owner's subscription at 30 %;
    - the worker's log has no new WARNING or ERROR;
    - the webhook still answers;
    - the first real signal after the deploy makes exactly one delivery.

### Delivery

- [x] C.D.1 Gate (backend and frontend), and an independent verifier over the whole PR. Backend after `6adb011`: ruff 0, mypy 0, pytest exit 0 with no failing test. Frontend after `ed2c724`, the last frontend change: lint 0, 102 files, 2,937 tests passed. Verifier: the C.V block, with the B1, B1a and B1b rechecks all closed.
- [x] C.D.2 Push and open the PR (on the owner's word). PR #88, opened 2026-10-29 from `54bdb2a` (27 commits over `origin/main` `7f67fc3`).
- [x] C.D.3 Merge (owner), with a merge commit: `214db9b`.
- [x] C.D.4 Deploy (C.13, C.14).
- [x] C.D.5 Delivery log row and "Production now".

### PR C's delivery

**PR C's deploy, 2026-10-29** (owner-run, one step at a time):
1. Pull as `strategy`, fast-forward `7f67fc3..214db9b`. No dependency changed, so no `uv sync`. The first attempt was typed inside an SSH session already on the VPS, which has no key to reach itself (`Permission denied (publickey)`); run from the owner's machine it worked.
2. **Backup and rehearsal (C.13).** The backup is `/root/sm_pre0031_20261029_1517.dump`, and the rehearsal ran on `sm_rehearsal_0032`, restored from it.
   - Production was at `0030`, with 1 user. Strategies: 3 live at 30 %, 3 archived at 5 %, each with exactly one author pool for its market. Live jobs: the six recurring chains, each `PENDING`.
   - Counts, the same in production and in the copy, and unchanged after `upgrade head`, after `downgrade 0030` and after the second upgrade:
     - `users` 1, `exchange_credentials` 8, `capital_pools` 5, `pool_balance_snapshots` 2;
     - `reservations` 13, `execution_attempts` 26, `ledger_entries` 83;
     - `reconciliation_discrepancies` 1, `booking_proposals` 0;
     - `strategies` 6, `signals` 54.
   - The ledger's `(id, xmin)` fingerprint was unchanged by each step.
   - After each upgrade: subscriptions `ACTIVE 30 3` and `ENDED 5 3`, one per strategy for its author, in a pool of its market, and none beyond the authors'; 54 deliveries for 54 signals, each with its signal's outcome and the author's subscription (`ACCEPTED` 17, `PROCESSED` 22, `REJECTED` 15); every reservation and attempt with its delivery; the constraints, the live unique index and the pool-market trigger present; the `reservations (signal_id)` unique dropped; `strategies.allocation_percent` nullable; both ledger triggers enabled (`O`).
   - 9 of the `ACCEPTED` deliveries open a position. They have no job and never run, and since `e1314bc` they make no close holder.
   - After the downgrade: every strategy's share restored and `NOT NULL` again, the new tables gone, the `signal_id` unique back.
   - The copy was dropped. Production was untouched, still at `0030`.
3. The worker was stopped (`inactive`) before the migration. The API stayed up: a signal received meanwhile would have waited in `signal.process` for the new worker.
4. `alembic upgrade head`: `0030 -> 0031`, `0031 -> 0032`.
5. Both services restarted, both `active`. Checkout `214db9b714ef`.
6. **pps.6.** The bundle was built from a clean worktree of `origin/main` at `214db9b714ef`: `npm ci` 0, build 0, 22 entries, SHA-256 `558eb57f1c96073ded6a4532acd83f09e553cf2f946140ff955a87eb5056f6cc`. The VPS printed `OK`, `readable`, and `214db9b714ef` for both bundle and checkout.
7. **Checks.**
   - Production: alembic `0032`; subscriptions `ACTIVE 30 3` and `ENDED 5 3`; `deliveries=54 signals=54`; live jobs only the six recurring chains.
   - No WARNING, ERROR or traceback from either service since the restart (16:26:45 CET).
   - The worker logged `1 enabled pools, dry_run=False`, `vault self-test: 1 sealed credential(s) opened (binance of user a90b5f44)` and `recurring chains already alive; nothing seeded`.
   - A POST to `/webhook/tradingview` answered `401`.
   - The owner loaded every page of the panel. The strategy page shows their share at 30 %, as before: it is now read from and written to their subscription.
   - **Pending:** the first real signal after the deploy makes exactly one delivery.

## PR D: per-strategy secret and authoring for any user

Design AD6, AD8, and decisions 21 and 23. Written 2026-10-29 from production at `0032` (main `214db9b`) and a read-only map of the code. Paths are relative to `backend/src/strategy_manager/`. Branch `feat/multi-user-authoring`.

Every signed-in user can author strategies, scoped to them, and each strategy authenticates its webhook with its own secret, stored as a hash. A strategy can be private (decision 21). The column PR C left unused, `strategies.allocation_percent`, is dropped. Access still admits only the owner, and the panel's admin gate stays until PR G, so production does not change in practice except for the secret flow.

**What the map found** (each is resolved in the tasks below):
- **a.** Ingress authenticates before it reads the body, with one global secret (`signals/infrastructure/router.py:119-130`, `auth.py:101-118`, constant-time). The strategy is known only from the payload's `signal_type` (`router.py:158-163`), so AD6 needs the strategy row before the secret check. An unknown strategy answers 422 `UNKNOWN_STRATEGY` today.
- **b.** The strategies router is admin-only at router level (`strategies/infrastructure/router.py:142-146`). `SqlAlchemyStrategyRepository` has no user-scoped read (`strategies/infrastructure/repository.py:49-120`). The pair catalogue is already scoped (`pair_catalog_router.py:91-100`, `read_available_pairs.py:37-40`) and only its admin guard changes.
- **c.** The create dialog always sends `allocation_percent = "100"` (`frontend/src/features/strategies/NewStrategyDialog.tsx:15,113`). The share still reaches the author's subscription through `StrategyPolicy.allocation_percent` (`register_strategy.py:164`, `author_subscription_adapter.py:44`), and the preview falls back to the column (`router.py:615-617`, N4).
- **d.** `GET /api/webhook-secret` (`signals/infrastructure/webhook_secret_router.py:55-65`) returns the global secret, and its test sweeps every `/api` route for it (`tests/signals/infrastructure/test_webhook_secret_router.py`).
- **e.** `strategies.name` is unique across all users (409 near `router.py:517`). Decision 23 makes it unique per author.
- **f.** The panel lets only admins in (`frontend/src/shared/auth/SignInGate.tsx:30`).

**Stated rather than asked (2026-10-29; the owner may overturn any):**
- **Ingress order:** source IP, then the body limit and JSON, then `signal_type`, then one read of the strategy by primary key, then the hash compare. An unknown strategy, a missing secret and a wrong secret all answer the same **401**, so an unauthenticated caller cannot probe which ids exist. `UNKNOWN_STRATEGY` goes away at ingress. An archived strategy is still accepted at ingress and refused in processing (operator-panel decision 11).
- **Shown once:** the create response carries the secret, and a new regenerate route returns a fresh one. Regenerating an archived strategy's secret is refused with 409, like every other write on an archived strategy.
- **Migrations:** PR D's 0033 holds the secret hash, the visibility, the per-author name unique and the column drop. PR E's mode columns move to 0034 (`design.md` "Migration plan" is updated with this).
- **Visibility default:** today's 6 strategies become PRIVATE, and the create form defaults to PRIVATE. Nothing turns public without the author's choice. It only matters from PR F, which opens the list.
- **The share at creation** travels in the command straight to the author's subscription, 100 by default as today. The create form keeps no share input; the share editor (C.12) changes it afterwards.
- **Scope of reads:** every user, the admin included, lists and reads only the strategies they author. Seeing other authors' strategies is PR F's public list.
- **Not in PR D:** the display name (decision 17) goes to PR F, the first place another user sees an author. The panel's admin gate opens in PR G, with Access. `Settings.webhook_secret` stays, because 0033 reads it in production; a later PR removes it with its startup invariant.

**Deploy shape:** 0033 drops a column the running code selects, so both services stop for the migration (unlike PR C, where the API stayed up). A signal posted in that window is lost, because TradingView does not retry, so the owner runs it away from a 4h candle close.

**Risk:**
- item 1: 0033 drops a column, rewrites a unique and backfills hashes;
- item 2: the webhook's authentication changes, and the strategy routes open from admin-only to scoped;
- item 3: `GET /api/webhook-secret` is removed, and the create response gains the secret.

It needs an independent verifier before the PR.

### Backend

- [x] D.1 Migration 0033 (AD6, decisions 21 and 23), and no code touches `strategies.allocation_percent` any more. Done on 2026-10-29.
  - `strategies.webhook_secret_hash text`: the SHA-256 hex of the current `Settings.webhook_secret` for every existing row, so today's TradingView alerts keep working unchanged. It refuses, naming nothing secret, when strategies exist and the setting is empty. The hash is computed in Python (`hashlib`); the secret never goes into SQL text or a log.
    - It stays NULLABLE here: until D.3 nothing writes it on create. D.3 adds `NOT NULL` to this same migration, together with `RegisterStrategy` writing it (the C.2/C.6 precedent; 0033 is not in production).
  - The share leaves the strategy (from D.4, moved here because dropping the column needs it): `AllocationPolicy.allocation_percent` and `StrategyPolicySnapshot.allocation_percent` go; `RegisterCommand.allocation_percent` stays and `subscribe_author` takes it as an argument; the repository stops writing and reading the column; the preview's fallback for a user with no subscription is 100 (N4). `AllocationPercent` stays, the subscriptions use it.
  - `strategies.visibility text NOT NULL` with CHECK `PUBLIC | PRIVATE`; existing rows `PRIVATE`.
  - The global unique on `strategies.name` is replaced by `UNIQUE (author_id, name)`. Find the old constraint's real name in the schema; do not guess it.
  - `strategies.allocation_percent` and its CHECK are dropped.
  - Downgrade: refuses unless exactly one user exists (as 0031); restores `allocation_percent` from each strategy's author subscription (the latest one), `NOT NULL` again; restores the global name unique; drops the two new columns.
  - Tests on real PostgreSQL through `migrated_database(name, "0032")`: the backfilled hash equals the setting's, the empty-setting refusal, visibility's CHECK and default, two authors may share a name and one author may not repeat one, the column gone, the downgrade and the upgrade again.
  - The ORM mirrors it: `StrategyRow` loses `allocation_percent` and gains both columns.
  - **Evidence (2026-10-29):**
    - `backend/migrations/versions/0033_strategy_authoring.py` and `tests/migrations/test_0033_strategy_authoring.py` (16 tests, real PostgreSQL, `WEBHOOK_SECRET` passed to the alembic subprocess: `wh-test-0033`, and `""` for the refusal and the empty database). The old name unique is found in `pg_constraint`, not guessed.
    - RED: before the migration existed, every test errored in its fixture with alembic's "Can't locate revision identified by '0033'". A migration test cannot fail on an assertion before its revision exists, so the proof of non-vacuity is the mutations below.
    - Mutations, each seen red on an assertion and then restored: skipping the hash `UPDATE` (`test_every_strategy_gets_the_hash_of_the_settings_secret`); disabling the empty-secret refusal (`test_refuses_when_strategies_exist_and_the_secret_is_empty`, `0 != 0` on the return code); the visibility default `PUBLIC` (`test_visibility_defaults_to_private`, `test_existing_strategies_are_private`); the downgrade picking the OLDEST subscription (`test_downgrade_restores_each_share_from_the_latest_author_subscription_and_upgrades_again`).
    - The downgrade restores `allocation_percent` NULLABLE (as it is at 0032 since 0031), not `NOT NULL` as the bullet above says: a strategy with no subscription would otherwise make it fail, and 0031's own downgrade is the step that makes it `NOT NULL` again. It refuses with more than one user (`found 2`).
    - Code: `AllocationPolicy.allocation_percent` and `StrategyPolicySnapshot.allocation_percent` removed; `subscribe_author(strategy, share)`, with `RegisterStrategy` validating the share (`AllocationPercent`) before the insert; repository and `StrategyRow` updated (`UniqueConstraint("author_id", "name", name="ux_strategies_author_name")`, `ck_strategies_visibility`); the preview's fallback is `Decimal("100")`.
    - Tests moved off the column: the share the single-subscriber signal tests carry now lives in a test-only `SnapshotWithShare` (`tests/signals/application/delivery_support.py`); `tests/owner.py::ensure_author_subscription` defaults to 100; the share-preview tests seed the owner's subscription instead of the strategy column, and "no subscription" now previews 100.
    - Focused runs: ruff 0, mypy 0 (341 files); `tests/strategies tests/signals tests/allocation tests/subscriptions tests/accounts` plus the 0033 file, one failure (`test_the_preview_completes_while_the_pools_advisory_lock_is_held`, fixed by seeding the owner's subscription), then green on rerun; `test_0031`, `test_0032` and `test_0033` pass together. The full suite is the parent's.
    - Parent review: the downgrade's share now comes from the AUTHOR's subscription (a join on `author_id`), as the text says, not from any user's; identical under the one-user guard. Gate after it: ruff 0, mypy 0, full pytest exit 0 with no failing test (the first run was stopped by the machine running low on memory, not by a failure).
- [x] D.2 The webhook authenticates per strategy (AD6, map a). Done on 2026-10-29.
  - A port reads one strategy's `webhook_secret_hash` by primary key. Ingress runs in the stated order and compares `sha256(secret)` with `hmac.compare_digest`.
  - `SourceIpAndSecretAuth` splits into the source check, which stays global and first, and the per-strategy secret check.
  - One 401 for unknown strategy, missing secret and wrong secret, with the same body. Tests: each of the three; another strategy's secret is refused (the reason AD6 exists); the body limit and the IP refusal still answer as today; an archived strategy's correct secret is accepted and refused in processing.
  - The webhook still does no write before authentication, and no read but the one strategy row.
  - **Evidence (2026-10-29):**
    - Writer (delegated, context backstop): `signals/application/ports.py` `StrategySecretReaderPort`; `signals/infrastructure/strategy_secret_reader.py` (one `SELECT webhook_secret_hash ... WHERE id`); `auth.py` is now `SourceIpAuth` plus `secret_matches_hash`, which fails closed on a missing or empty secret and on a NULL hash. Every secret failure answers 401 `{"detail":"unauthorized"}` and logs nothing; the secret still travels in `?secret=`.
    - `tests/signals/infrastructure/test_per_strategy_secret_ingress.py`: 9 tests seen red on assertions before the code (own secret 401, cross-strategy, global secret 200, unknown 422, NULL hash 200, 413 and 422 answered 401, zero SELECTs, archived 401). Mutations seen red, then restored: skipping the IP check, accepting a `None` secret, `secret_matches_hash` always true, logging the hash on refusal.
    - Expectations changed: an oversized body is 413 whatever the secret, because the limit now comes before the secret (the body-never-read claim for a stranger lives on the IP test); an unknown strategy is 401, not 422 `UNKNOWN_STRATEGY`. The router's `UNKNOWN_STRATEGY` branch stays only for a strategy deleted between the hash read and the insert (race test with a patched reader).
    - Parent review: the writer validated the WHOLE alert before the secret. TradingView's addresses are shared by every TradingView user, so that let anyone get the alert's 422 detail and a warning log line without the secret. Now only `signal_type` is read before the secret; an alert that names no usable strategy is still refused for its shape, as before. `test_the_rest_of_the_alert_is_judged_only_after_the_secret` was seen red on its assertion (422 instead of 401) before the fix. `test_a_refused_alert_is_answered_without_the_secret` now seeds a strategy with that secret. Gate after it: ruff 0, mypy 0, full pytest exit 0 with no failing test.
- [x] D.3 Issue and regenerate the secret (AD6). Done on 2026-10-29.
  - `RegisterStrategy` generates 32 random bytes (`secrets.token_urlsafe(32)`), stores only the hash, and the create response carries the secret once.
  - `POST /api/strategies/{id}/webhook-secret` (author only, AD8 404 otherwise; 409 when archived) replaces the hash and returns the new secret once. The old secret is refused from then on.
  - `GET /api/webhook-secret` and its router are removed. The sweep in `test_webhook_secret_router.py` becomes: no `/api` response body other than these two contains a strategy's secret, and none contains a `webhook_secret_hash`.
  - No log line carries a secret or a hash.
  - **Evidence (2026-10-29):**
    - Writer (delegated, Sonnet, per the large-unit token scheme): `strategies/domain/webhook_secret.py` (`new_webhook_secret`, `hash_webhook_secret`); `RegisterStrategy.register` returns a `Registration(strategy, webhook_secret)` whose repr hides the secret; new `strategies/application/regenerate_webhook_secret.py` (reads the row with `get_by_id_for_update`, as `UpdateStrategy` does; no pool lock, it touches no capital). The hash stays out of the domain read model: the repository's `insert(strategy, webhook_secret_hash)` and `replace_webhook_secret_hash` are the only ways in, so no `Strategy` read carries it. Create and regenerate answer `Cache-Control: no-store`.
    - 0033 sets `webhook_secret_hash NOT NULL` after the backfill, and `StrategyRow` mirrors it. Every test insert of a strategy now carries a hash (the conftests of allocation, ledger, execution, reconciliation and signals, and the strategies integration tests); migration tests at revisions before 0033 are untouched.
    - `signals/infrastructure/webhook_secret_router.py` and its wiring are gone. `tests/signals/infrastructure/test_no_api_response_carries_a_webhook_secret.py` replaces its test: across every `/api` route, no body or header carries the global secret, the strategy's secret, its stored hash or the name `webhook_secret_hash`, and only the create and regenerate routes name `webhook_secret`, without the new secret's hash. A caplog test over create, regenerate and a refused regenerate finds no secret or hash.
    - Expectations changed: a strategy with a NULL hash can no longer exist, so `test_a_strategy_with_no_hash_accepts_no_secret` went and the four-refusals test became three; `seed_strategy` gives every strategy a secret by default.
    - TDD: the writer wrote the code before the tests, so there is no RED-first run for D.3. Non-vacuity was proven by mutations, each seen red and restored. The writer's: the author check removed (`(200, 404) == (404, 404)`), the secret logged after commit, the plain secret stored instead of its hash (three tests), the `NOT NULL` skipped (two tests, "DID NOT RAISE"). The parent's, on what the writer left unmutated: a `webhook_secret_hash` field on `StrategyView` (the sweep failed on `GET /api/strategies`, `GET /{id}` and `PATCH /{id}`); the regenerate answer carrying the new secret's hash (failed on that route); the regenerate path without the row lock (`test_regenerating_waits_for_the_strategy_row_lock`, `200 == 409`).
    - Parent fixes: `tests/shared/infrastructure/test_spa.py` used `/api/webhook-secret` as its known route, so it now uses `/api/webhook-origin` (GET for 200 and 401, DELETE for 405); a stale docstring in `webhook_origin_router.py`. Left as is: a few unused fake repositories in unit tests still have the old `insert` signature; nothing calls them. Gate after it: ruff 0, mypy 0, full pytest exit 0 with no failing test.
- [x] D.4 Authoring for any signed-in user (AD8, decision 23, map b and c).
  - The strategies router and the pair-catalogue router take `current_user` instead of `require_admin`.
  - The repository gains author-scoped reads, and every route reads through them: another user's strategy answers 404 on `GET /{id}`, `/events`, `/share-preview`, `PUT /allowed-pairs`, `PATCH`, `archive`, `DELETE` and the regenerate route, each with its cross-user test.
  - `GET /strategies` lists the user's own strategies.
  - A repeated name answers 409 only within one author; the refusal says nothing about other users' strategies.
  - (The share leaving the strategy moved to D.1.)
  - Every test that relied on the admin guard still holds for a non-admin author.
  - **Evidence (2026-10-29):**
    - Writer (delegated, Sonnet): `AuthorStrategyRepository(session, author_id)` in `strategies/infrastructure/repository.py` filters `get_by_id`, `get_by_id_for_update` (still `FOR UPDATE`, `populate_existing`) and `list_all` by author. Every strategies route builds its use case on it, so another user's strategy is `UnknownStrategy` and the same 404 as a missing one, with the use cases unchanged; `RegenerateWebhookSecret` drops its own author check and relies on it. The strategies and pair-catalogue routers take `current_user`. `is_name_conflict` reads the violated constraint's NAME (`ux_strategies_author_name`); any other `IntegrityError` is no longer reported as a name clash. `RegisterStrategy`'s id-collision 409 names the existing strategy only to its own author.
    - `tests/strategies/infrastructure/test_strategy_authoring_scope.py` (29 tests). RED on assertions before the code: a non-admin's create, read, PATCH, allowed-pairs, archive, delete, regenerate and pair catalogue (`403`); every cross-user route (`(200, 404) == (404, 404)`, delete `(204, 404)`); the id-collision text naming another user's strategy; another constraint answering 409 instead of 500. The two `AuthorStrategyRepository` unit tests were red on an ImportError, not an assertion. Mutations seen red, then restored: the regenerate route on the unscoped repository; `is_name_conflict` always false; `.with_for_update()` dropped from the scoped read (`test_the_scoped_locked_read_waits_for_the_row_lock`); the model's unique on `name` alone. `test_the_admin_authors_exactly_as_before` and the non-admin pool-404 test passed at once and were not mutated.
    - Expectations changed: a user who is not the author now gets 404 instead of 403 on regenerate; the `test_router_auth.py` non-admin 403 sweep became a structural check (no `require_admin`, `current_user` on the router); share-preview and strategy-view tests that read the owner's strategy as another user now expect 404, since reading another author's strategy waits for PR F; `test_every_api_route_is_guarded.py` lists the ten strategies and pair routes as scoped to the signed-in user, and its admin-only floor went from 10 to 3.
    - Kept unscoped on purpose: `get_register_strategy`'s id lookup (ids are global) and the base repository for non-router callers (the fan-out, the worker).
    - Gate (parent): ruff 0, mypy 0, full pytest exit 0 with no failing test.
- [x] D.5 Private strategies (decision 21). Done on 2026-10-29.
  - The create request takes `visibility` (default `PRIVATE`); `PATCH /{id}` changes it, author only.
  - `Subscribe` refuses another author's private strategy as `StrategyNotFound`, 404, the same answer as a strategy that does not exist (`subscriptions/application/subscribe.py:44-48`). The author's own private strategy is not refused.
  - Making a strategy private keeps its current subscribers, and the fan-out never reads visibility. A test pins that a private strategy's existing subscription still gets its delivery.
  - **Evidence (2026-10-29):**
    - Writer (delegated, Sonnet): `Visibility` (PUBLIC/PRIVATE) in `strategies/domain/strategy.py`, carried by `Strategy` (default PRIVATE), `RegisterCommand` and `UpdateCommand`, persisted by the repository and shown on `StrategyView`; an invalid value is a 422. `Subscribe` refuses another author's PRIVATE strategy with the same `StrategyNotFound` text as a missing one; `StrategyMarket.visibility` is required, so no caller can skip the check. A PATCH with `"visibility": null` leaves it unchanged, like the other optional fields.
    - `tests/strategies/infrastructure/test_strategy_visibility.py` (7), three tests in `tests/subscriptions/infrastructure/test_subscriptions_router.py`, one in `tests/signals/infrastructure/test_fan_out_integration.py`. RED: another author's private strategy `(201, 404) == (404, 404)`; an invalid value `(201, 200) == (422, 422)`; the default, the create, the change and the untouched-on-PATCH tests on a `KeyError: 'visibility'` in the response body (the field did not exist yet). Mutations seen red, then restored: the author's exemption dropped (own private strategy 404); refusing on authorship alone (another's public strategy 404); the PATCH on the unscoped repository (`200 == 404`); the archived check skipped for visibility (`200 == 409`); the repository not writing visibility (`'PRIVATE' == 'PUBLIC'`); a visibility filter in the fan-out's subscriber read (`set() == {delivery}`; the file was restored and is unchanged).
    - Test seeds: `tests/subscriptions/infrastructure/seeds.py::strategy()` defaults to PUBLIC, because the existing subscribe tests subscribe a user who is not the author and the column's default is PRIVATE. No existing expectation changed.
    - Gate (parent): ruff 0, mypy 0, full pytest exit 0 with no failing test.

### Frontend

- [x] D.6 The panel's secret flow and visibility (EN/ES). Done on 2026-10-30.
  - The create dialog offers the visibility choice (default private) and, after creating, shows the webhook URL with its secret once, with a copy button and a warning that it will not be shown again.
  - The strategy header's webhook message shows the URL with a placeholder, and a regenerate action with a confirmation that the old secret stops working. "Show secret" and `shared/api/webhook-secret.ts` go away.
  - The strategy page shows and changes the visibility.
  - The name conflict message no longer implies the name is taken system-wide.
  - **Evidence (2026-10-30):**
    - Writer (delegated, Sonnet): `shared/api/types.ts` (`Visibility`, `Strategy.visibility`, `RegisteredStrategy`); `shared/api/strategies.ts` (`regenerateWebhookSecret`, `setStrategyVisibility` and their hooks; both secret-holding mutations use `gcTime: 0`, so the secret leaves the mutation cache when its view unmounts); `shared/api/webhook-secret.ts` deleted. New `CopyAction`, `IssuedWebhookUrl` (the one "shown once" view, used by create and regenerate), `RegenerateSecretDialog`, `VisibilityField`, `VisibilityControl`; `WebhookMessage`, `NewStrategyDialog`, `StrategyHeader` and `StrategyDetailPage` changed; EN and ES copy, ES in "usted". The secret is in no storage, console line, panel URL or long-lived cache.
    - RED before the code: 22 of 27 `WebhookMessage` tests and 9 of 9 `VisibilityControl` tests (the latter on "Unable to find a label" for the control under test, not an assertion), the new and changed `NewStrategyDialog` tests and the rename 409 text. Mutations seen red, then restored: `archived={false}` on the header (two tests); `gcTime: 0` removed from regenerate (the header collapse test and three `WebhookMessage` tests) and from register (the "secret is nowhere after Done" test); the archived guard in `VisibilityControl`.
    - Expectations changed: the Show/Hide-secret and Copy-URL-while-hidden tests went with those controls; the create dialog stays open on its issued URL until Done; the 409 text says the user already has a strategy with that name. `visibility` was added to the `Strategy` fixtures, four of them under `features/positions` (fixture field only).
    - Behaviour choices (the second one is decision 24, confirmed 2026-10-30): the header keeps only Copy message (a Copy URL there would copy the placeholder); in the issued view Copy stays enabled with no webhook host configured and copies the path with a note to put the host in front, unlike decision 53, which disabled Copy with no host, because otherwise a secret shown once could not be copied at all.
    - Parent check: `npm run lint` exit 0; `npm test` 2889 passed of 2889.

### Independent verification (2026-10-30)

An Opus verifier read the whole PR D section, AD6, AD8 and decisions 21 and 23, and probed `7258fac` against the baseline `214db9b` in a scratch directory outside the workspace (since removed), on throwaway PostgreSQL databases.

- **Verdict: no blockers.** D.1-D.6 PASS.
- 0033 on a copy shaped like production (1 user, 6 strategies, 3 archived, subscriptions at 30 and 5): the empty-secret refusal changes nothing and names nothing secret; every hash equals sha256 of the setting, a non-ASCII secret included; neither appears in alembic's output; subscriptions and the other strategy columns are byte-identical after the upgrade and after the downgrade; the downgrade refuses with 2 users and with 1 restores 30, 30, 30, 5, 5, 5; upgrading again works.
- Ingress: unknown id, missing, empty, wrong, another strategy's, the old global secret and the stored hash sent as the secret all answer one byte-identical 401 (status, body, headers), identical to the IP refusal; nothing written, no log record; the access log shows `secret=REDACTED`.
- Ten cross-user calls each answer the same 404 as a missing id, with no data change. Create and regenerate are no-store; no other `/api` answer carries the secret, the hash or the name.
- **Advisories:**
  - The 0033 downgrade restored `allocation_percent` without 0032's `DEFAULT 100`. **Fixed:** `test_the_downgraded_share_column_gets_back_its_default` was seen red on its assertion (`None == "'100'::numeric"`), then green; the 0031, 0032 and 0033 migration tests pass together.
  - At baseline already: `GET /api/performance/strategies/{id}` reads strategies unscoped, so another user's strategy, a private one included, answers differently from a missing id. For PR F, where other users' strategies become readable.
  - At baseline already, and a stated choice: an alert with a stale secret after a regenerate is a 401 with no log line, so the signal is lost without a trace.
  - From PR G: `/api/webhook-origin` is still admin-only, so a non-admin author's issued URL would carry only the path.
  - Escape closes the create dialog's shown-once view without a confirmation, and the secret is gone (regenerate recovers it).
  - A concurrent create with the same id is now a 500 (a primary-key `IntegrityError`) instead of the old, wrong, name 409.

### Rehearsal and deploy (owner-run)

- [x] D.7 Before the deploy: a fresh backup, then rehearse 0033 on a throwaway restore, with a downgrade to 0032 and a second upgrade.
  - Script ready (2026-10-30): `rehearse_0033.sh`, kept in the session scratchpad and piped through `ssh ... "bash -s"`. It prints no DSN, secret or hash: it reads `WEBHOOK_SECRET` from the same `.env` alembic reads, hashes it in the shell and hands the hash to psql on stdin only. It checks counts, the ledger, the subscriptions and the strategy columns 0033 does not touch are unchanged across the upgrade, the downgrade and the second upgrade; every hash equals the current secret's (the condition for today's alerts to keep working); every strategy PRIVATE; the per-author unique and no global one; the column dropped; and, after the downgrade, the global unique back, `allocation_percent` nullable with its default 100 and each share its author's latest subscription's.
  - Rehearsed locally on a copy of the dev database brought to 0032 (4 strategies, 4 subscriptions): every check ok, exit 0. Its first run stopped on a bug of the script's own local mode (the secret cleared before alembic used it), fixed. Mutation: hashing a different secret stopped it with "4 strategies have another hash", then restored.
  - Counts and the ledger's `(id, xmin)` unchanged.
  - Every strategy has a hash equal to `sha256` of the current setting (compared on the VPS, printing only `ok`), and is `PRIVATE`.
  - The name unique is per author; `allocation_percent` gone; the downgrade restores each share from the author's subscription.
- [x] D.8 Deploy (2026-10-30, see "PR D's delivery"; the first-real-signal check and the visibility on the strategy page are still open):
  1. pull as `strategy`;
  2. away from a 4h candle close, stop both services;
  3. `alembic upgrade head`;
  4. start both services;
  5. pps.6 for the panel.
  - Check:
    - a POST with no secret and one with a wrong secret both answer 401;
    - the panel and every page load, and the strategies show as private;
    - no new WARNING or ERROR in either service;
    - the first real signal after the deploy authenticates with the alert's unchanged URL and makes exactly one delivery.

### Delivery

- [x] D.D.1 Gate (backend and frontend), and an independent verifier over the whole PR. Done on 2026-10-30: the full backend gate was green after every unit and in the verifier's run at `7258fac`; frontend lint 0 and 2889/2889; the one fix after it touches only 0033's downgrade, whose migration tests (0031, 0032, 0033) and ruff pass.
- [x] D.D.2 Push and open the PR (on the owner's word). PR #89, opened 2026-10-30 from `9eea362` (11 commits over `origin/main` `214db9b`).
- [x] D.D.3 Merge (owner), with a merge commit: `d75e5a4` (parents `214db9b`, `541bd16`).
- [x] D.D.4 Deploy (D.7, D.8), 2026-10-30.
- [x] D.D.5 Delivery log row and "Production now".

### PR D's delivery

**PR D's deploy, 2026-10-30** (owner-run, one step at a time):
1. Pull as `strategy` to `d75e5a4`. No dependency changed.
2. D.7: `rehearse_0033.sh` through `ssh ... "bash -s"`: fresh backup `/root/sm_pre0033_<UTC>.dump`, the copy upgraded, downgraded to 0032 and upgraded again, every check ok (the owner: "El ensayo pasó").
3. D.8: `deploy_0033.sh` checked the checkout (`d75e5a488cc6`) and the version (`0032`), stopped both services and migrated `0032 -> 0033`; every strategy's hash equalled the current secret's. It then **stopped on a diagnostic query of its own** (`GROUP BY 1` over an expression holding `count(*)`: "aggregate functions are not allowed in GROUP BY"), after the migration and before starting the services, so both stayed stopped until the owner started them by hand. The query was not in the rehearsal, so nothing had run it. `deploy_0033_finish.sh`, with the query fixed and tried on local PostgreSQL first, ran the remaining checks; the owner: "Todo correcto". Stopping the API left it `failed`, not `inactive` (uvicorn probably exits non-zero on the stop signal); it came back `active` on start.
4. pps.6: built by the assistant from a detached worktree of `origin/main` at `d75e5a488cc6`, 22 entries, SHA-256 `e89c367a1c7c513bfab4f79c9c63971392532ab83a30d7264272be6ad8398886`; the owner's block printed `/root/panel-d75e5a488cc6.tgz: OK`, `readable`, `bundle:   d75e5a488cc6` and `checkout: d75e5a488cc6`.
5. The panel: the owner saw the "Regenerate secret" action. They did not see the visibility ("Privada") on the strategy page; the control sits in the page's settings block, below the allowed pairs. Open until the owner looks there again.

**Lesson:** every query a deploy script runs is exercised locally before it is handed over, not only the rehearsal's. A check that can fail goes before the step that cannot be left half done, or after the services are back.

**Still open:** the first real signal after the deploy authenticates with the alert's unchanged URL and makes exactly one delivery (C's open check too).

## PR D2: the webhook secret's last four (decision 25)

Written 2026-10-30, after PR D's deploy, from the owner's request to mask the secret on the strategy page "como las claves API". Branch `feat/webhook-secret-hint`, cut from `main` `d75e5a4`.

The strategy page shows the webhook URL with the secret masked by its last four characters (`***` and the four), as an API key's hint is shown, instead of the `<your secret>` placeholder. Only a hash of the secret is stored, so the four characters are kept apart, written whenever a secret is issued.

**Defaults, stated rather than asked:**
- The API names the field `secret_last4`, never with `webhook_secret` in it: the PR D sweep forbids that name in every answer but the two that issue a secret. The column is `strategies.webhook_secret_last4`.
- 0034 backfills every existing strategy with the last four of today's `WEBHOOK_SECRET`, computed in Python from the setting as 0033 did, and refuses when strategies exist and the setting is empty or shorter than four characters, or when a strategy's hash is not the setting's (a secret of its own; added after the verifier's advisory 1). It is `NOT NULL`, with a CHECK on four characters.
- ~~The header's Copy message copies the masked URL, as it copied the placeholder.~~ Wrong premise, corrected 2026-10-30: Copy message copies the alert's JSON, which holds no secret, and since D.6 the header has no Copy URL; nothing copies the masked URL.
- The deploy needs no stop: 0034 only adds a column the running code does not select, so it migrates with both services up, then both restart and pps.6 runs.

**Risk:** item 1 (0034 backfills from a setting); item 2 (characters of a secret reach an API answer). It gets an independent verifier before the PR.

- [x] H.1 Store and serve the last four (backend).
  - 0034, with tests on real PostgreSQL through `migrated_database(name, "0033")`: the backfill equals the setting's last four; the refusals; `NOT NULL` and the CHECK; the downgrade drops the column and the upgrade runs again.
  - `RegisterStrategy` and `RegenerateWebhookSecret` write the hash and the last four together through one helper; the repository takes both and still keeps them out of the domain read model's other uses; `StrategyView` carries `secret_last4`.
  - Regenerating changes it; another user still gets the same 404; no log line carries it with the rest of the secret.
  - The PR D sweep still holds: no answer carries the secret, its hash or a `webhook_secret` name outside the issuing routes; it gains: the list and `GET /{id}` carry exactly the last four of the strategy's current secret, and nothing longer.
- [x] H.2 The panel masks with the last four (EN/ES).
  - The header's webhook URL shows `***` and the last four in place of the secret, styled as the credentials' last-four hint; the hint text says what the four characters are for. (Copy message copies the alert's JSON, as before; see the corrected default above.)
  - The `<your secret>` / `<su secreto>` placeholder goes.
- **Evidence for H.1 and H.2 (2026-10-30, one Sonnet writer, both tasks as one behaviour):**
  - `0034_webhook_secret_last4.py`: backfills the setting's last four in Python, then `NOT NULL` and `ck_strategies_webhook_secret_last4_length`; refuses, naming nothing secret, when strategies exist and the setting is shorter than four characters. `webhook_secret_last4` in `strategies/domain/webhook_secret.py` is the one helper; register and regenerate write hash and last four together (`replace_webhook_secret(id, hash, last4)`, renamed from `replace_webhook_secret_hash`). `StrategyView.secret_last4` is read through a separate author-scoped query (`AuthorStrategyRepository.secret_last4s`), so no domain `Strategy` carries it.
  - Panel: `Strategy.secret_last4` (the guard requires exactly four characters); `WebhookMessage` draws `***` and the four in the same classes as the credentials' `KeyHint`, with a hint line in EN and ES; the placeholder is gone; regenerate invalidates the strategy reads on success so the new four show.
  - RED on assertions before the code: the helper (`'' == 'wxyz'`), the register, repository and regenerate tests (`'????' == 'wxyz'`), 25 `WebhookMessage` tests, the guard and the invalidation tests. The 0034 tests, which cannot fail on an assertion before the revision exists, by mutations seen red and restored: backfill from the first four; the refusal weakened to an empty setting only; the CHECK loosened. Passed at once and then mutated: the reads' exactly-four test and the sweep (a constant in `StrategyView.of`), the author scope of `secret_last4s` (filter removed), three panel tests.
  - Raw strategy inserts in about 20 test files gained the column (sentinels `"cret"`, `"fxtr"`), and 16 panel fixtures `secret_last4`.
  - Writer's checks: ruff over `src`, `tests` and 0034 clean; mypy 0; the 0033 and 0034 migration tests, `tests/strategies`, the sweep and 17 other touched files exit 0; `npm run lint` 0; `npm test` 104 files, 2901 passed.
  - Owner's request after seeing the page (2026-10-30), done inline by the parent: "prefiero que esté arriba de todo, compartiendo el ancho con el titulo 'Settings of this strategy'. De paso acortar dicho titulo a simplemente 'Settings' o 'Strategy settings'. Agregale al desplegable un icono tipo mundo 🌐 para public y candado para private." The visibility select now shares the settings heading's row, above the share; the heading reads "Strategy settings" / "Ajustes de la estrategia"; the select draws the selected value's `lucide-react` icon (`Lock` private, `Globe` public), in the create dialog too. Beside the heading the label and the hint are kept for screen readers and the hint shows on hover, so the select fits the row. RED on assertions before the code (the heading's text, then no icon for either value); `npm run lint` 0, `npm test` 104 files, 2904 passed.
  - Found on the way: the docstring line the parent added to 0033 in `dc8e0f7` broke ruff's E501, and reached `main` because ruff was not rerun after that edit. Rewrapped here (the first rewrap still overflowed by one character; the gate caught it).
  - Gate (parent): mypy 0, full pytest exit 0 with no failing test; ruff 1 on that rewrap, fixed, then ruff 0. Frontend lint 0, 2904 passed.
- **Independent verification (2026-10-30, Opus, `dbf3786` against `d75e5a4`): no blockers; H.1, H.2 and the layout request PASS.**
  - 0034 probed on real PostgreSQL on a production-shaped copy (1 user, 6 strategies, 3 archived, subscriptions at 30 and 5): the backfill gives four characters for an ASCII, a non-ASCII BMP and an astral secret; every other table's data and the schema equal the 0033 snapshot apart from the new column and its CHECK; the downgrade restores 0033 exactly and the upgrade runs again; the four refusals (`""`, `abc`, three BMP characters, three emoji) leave 0033 and the data unchanged, through `upgrade 0034` and `upgrade head`, naming no character of the secret.
  - Register and regenerate cut hash and four from one secret in one flush and one commit; `secret_last4s` is author-scoped; no log statement in the strategies module touches the secret, its hash or the four. Panel: `***` and the four, the exactly-four guard, invalidation on success only, the shown-once flow unchanged, EN/ES copy.
  - Verifier's commands: the 0033 and 0034 migration tests, `tests/strategies` and the sweep exit 0; its 8-case 0034 probe exit 0; `npm run lint` 0; `npm test` 104 files, 2904 passed.
  - Advisories:
    1. 0034 cannot tell a strategy whose secret is its own: any strategy registered or regenerated since PR D's deploy gets the setting's four, silently, and the panel shows four characters that are not its secret's. **Fixed on the owner's word (2026-10-30, "Si, por favor"):** 0034 also refuses, before anything is written, when any strategy's hash is not the hash of the setting, naming only how many; the message names no character of either secret and no hash. RED on an assertion first (`test_refuses_when_a_strategy_has_a_secret_of_its_own`: `assert 0 != 0`); the module's strategies are now seeded with the setting's real hash rather than `'fixture-hash'`, as 0033 leaves them. Gate after it: ruff 0, mypy 0, full pytest exit 0 with no failing test.
    2. The panel's guard measures the four with JS `.length` (UTF-16 units), so a setting ending in astral characters makes the list and the detail fail to load. Out of domain for an ASCII or BMP secret.
    3. The mask draws the four without percent-encoding, while the shown-once URL encodes the secret. Cosmetic, and only for a setting with characters that are not URL-safe.
    4. A refetch that fails after every retry following a regenerate swaps the page to its error branch and loses the shown-once secret. A failed background refetch did the same at baseline.
    5. Stale wording: this task line (fixed), some `WebhookMessage` test names still say "placeholder", an odd wrap in `regenerate_webhook_secret.py`'s docstring; `_view` and `list_strategies` index `last4s[id]`, so a delete racing the read answers 500 rather than 404.
- [x] H.3 Rehearsal and deploy (owner-run): a fresh backup, 0034 rehearsed on a throwaway restore with a downgrade to 0033 and a second upgrade; then pull, migrate with the services up, restart both, pps.6. Every query a script runs is exercised locally first (PR D's lesson).
- [x] H.D Gate, independent verifier, then push and PR on the owner's word, merge, deploy, delivery log.

### PR D2's delivery

**Before the handover (2026-10-30).** `rehearse_0034.sh` and `deploy_0034.sh` ran whole against the local PostgreSQL, with the service commands stubbed in the deploy's local mode, on a copy of the dev database brought to 0033 with a throwaway secret: both exit 0. With one strategy given a hash of its own, both stopped with exit 1 and the copy stayed at 0033. Both scripts check for such a strategy before the backup or the migration, so a refusal changes nothing.

**PR D2's deploy, 2026-10-30** (owner-run):
1. Pull as `strategy` to `ddf8262`; `rehearse_0034.sh`; `deploy_0034.sh`, which migrates with both services up and restarts both. The owner reported the steps done and pasted only the panel block's output, so these outputs are not recorded. What confirms them: the panel shows `***` and four characters, which only the restarted code at 0034 can serve.
2. pps.6: built by the assistant from a detached worktree of `origin/main` at `ddf82629b572`, `npm ci` 0, build 0, 22 entries, SHA-256 `253e482844d0a546136b5e64013a98194d2d206c2ff4c5d7f280c5c6837f14c9`; the owner's block printed `/root/panel-ddf82629b572.tgz: OK`, `readable`, `bundle:   ddf82629b572` and `checkout: ddf82629b572`.
3. The panel, read by the owner: "El panel muestra correctamente la URL enmascarada y la visibilidad al lado del titulo con su icono". This also closes PR D's open point about the visibility on the strategy page.

**The first real signal after PR C (read by the owner, 2026-10-30):** `SFPUSDT.P` buy received 2026-10-30 12:00:03 UTC: one ACTIVE subscription, one delivery `PROCESSED`, one reservation `FILLED` at 322.89, one attempt `FILLED`, 12 fills. The signal's own `status` reads `ACCEPTED`, as designed since C.7: after a fan-out that delivered, the outcome lives on the delivery. This closes PR C's check for an opening.

**Still open:** that signal predates PR D's deploy (the owner reported it at about 14:48 UTC), so it authenticated with the old global secret. The first signal after that deploy must authenticate through the strategy's hash with the alert's unchanged URL and make exactly one delivery. The close of this SFP position is the likely first one, and it also proves a close's delivery. A wrong secret answers a 401 and logs nothing, so a close that TradingView fired and the panel never shows must be raised at once: the position would stay open. **Closed 2026-10-31**, under PR E's delivery.

## PR E: the mode belongs to the user (AD7, decisions 6, 7, 13, 14, 26)

Written 2026-10-30, after PR D2's deploy, from a read-only map of today's code. Branch `feat/multi-user-mode`, cut from `main` `ddf8262`.

The rule: a delivery opens LIVE only if `.env` `DRY_RUN` is false and the user's `mode` is `LIVE`; otherwise it opens in simulation, against the user's real balance. The mode is recorded on the reservation at open, and everything after that (the order, its settle, the close) follows the reservation, never the brake or the user's current mode. Production must trade exactly as before: the owner is `LIVE` and `DRY_RUN=false`.

**What the map found, which the design did not say:**
- No column records a mode today. "Rehearsal" is only the `fake-fill-` and `fake-order-` prefixes.
- `exchange_for(session, user_id)` is entered before a job reads its reservation, so a job cannot yet pick an adapter by the recorded mode. A REVERSE can need two modes in one job: the close's and the reopening's.
- A close never reads its reservation row; a recorded mode needs its own read there.
- `FakeVenueBook` is one process-wide book keyed `(exchange, market)` and seeded from every ledger row, and the fakes exist only under `DRY_RUN=true`. `tradable_pools` is computed once, from either the fakes or the live classes.
- `balance.sync`, the on-demand balance refresh and the vault self-test already use the real key whatever the mode. Nothing there changes.
- A scan compares the ledger with the venue, and the ledger holds `fake-fill-` rows, so scanning a user with simulated positions would report the rehearsal itself as a discrepancy.

**Defaults, stated rather than asked:**
- `users.mode` is `LIVE | SIMULATION`, `NOT NULL`, default `SIMULATION` (decision 6). 0035 sets existing users to `LIVE` when `DRY_RUN=false` at migration, else `SIMULATION`, read from the setting as 0033 read the secret.
- `reservations.mode` is `NOT NULL` with **no default**: a writer that forgets it fails loudly instead of recording a wrong mode. Backfill, per reservation: any `fake-` fill or order and no real one is `SIMULATION`; any real fill or order is `LIVE`; no evidence (no order ever reached a venue) takes the mode the users get. 0035 refuses, writing nothing, when an **open** allocation holds both real and fake fills; a closed one is `LIVE`, since real money moved.
- Under the brake the server refuses any mode change (409 `MODE_BRAKE_ON`), as the badge cannot be clicked.
- `/api/me` gains `mode` and replaces `dry_run` with `dry_run_brake`; the panel is its only reader. `/health` stays as it is, for monitoring. The keyed exchanges AD11 lists on `/api/me` wait for PR F, which is what reads them.
- Under the brake reconciliation stays skipped as it is today. With the brake off it skips users in simulation with nothing real open, and it compares only real fills with the venue.
- The startup guard keeps checking mismatches, now between a reservation's recorded mode and its fills, and it gains AD7's refusal: a real open allocation whose user has no active trade-capable key.
- 0035 needs both services **stopped**: running code inserts reservations without `mode`.

**Risk:** item 1 (0035 backfills what decides a real close); item 3 (`/api/me`'s shape); item 4 (the race between a flip and an opening). It gets an independent verifier before the PR.

- [x] E.1 The columns (backend).
  - `Mode` in the domain, and a pure `effective_mode(brake, user_mode)`: `LIVE` only for brake off and `LIVE`.
  - 0035 with tests on real PostgreSQL through `migrated_database(name, "0034")`: each backfill case, the refusal, the CHECKs, a new user's default, a reservation without a mode refused, downgrade and a second upgrade. The test seeds both `DRY_RUN` values.
  - The nine test files that insert reservations by hand gain the column.
- **Evidence for E.1 and E.4's allocation half (2026-10-30, the parent for 0035 and `Mode`, one Sonnet writer for the rest, the parent for the pools panel):**
  - `Mode` and `effective_mode` in `shared/domain/mode.py`, since allocation, execution and identity all read them. RED on an assertion first (`LIVE is SIMULATION`, the stub ignored the brake).
  - 0035 cannot fail on an assertion before the revision exists, so by mutations seen red and restored: real evidence loses to simulated; closing orders, orders, or fake orders not read as evidence; no refusal; the refusal ignoring the net; users not backfilled; the brake ignored; users defaulting to `LIVE`; the column left nullable; each CHECK gone; the downgrade not refusing. A fourteenth mutation meant for "no evidence is always `LIVE`" produced invalid SQL, so it proved nothing; "the brake ignored" covers that rule.
  - `Reservation.mode` is required with no default and `User.mode` required; `UserModePort`, with `SqlAlchemyUserMode(session, brake=...)` reading `FOR SHARE`, is called right after the pool advisory lock; `sum_active` takes the mode (decision 26).
  - The writer did not work test-first: adding required fields breaks every fixture with constructor errors. Its tests are proven by mutations seen red and restored: the mode hard-coded in `AllocateCapital`; the read moved before `acquire`; `sum_active` without the mode filter (`PARTIAL is FULL`, `130 == 100`); the brake ignored; `FOR SHARE` removed. That last one fails on the recorded mode, not on `not task.done()`: without `FOR SHARE` the opening still blocks on the foreign key's `FOR KEY SHARE` at the insert, having read the old mode. So the recorded mode is what pins it.
  - Found on the way: `GET /api/pools` calls `sum_active`. It now takes the user's effective mode, so the panel shows what the next opening would get (decision 26). RED on an assertion first (`300 == 7`, with the mode fixed to `LIVE`).
  - `test_0029_users.py` asserts the head schema's `users` columns, so it gains `mode`.
  - Gate: ruff 0, mypy 0, full pytest with that one test failing and nothing else (a first run was stopped by the machine's low memory); the test fixed and its file rerun.
- [x] E.2 The user's mode (`POST /api/me/mode`).
  - `GET /api/me` answers `mode` and `dry_run_brake`.
  - `POST /api/me/mode` takes the user row `FOR UPDATE`. To `LIVE`: 409 `MODE_LIVE_NEEDS_TRADE_KEY` without an active trade-capable key on some exchange. To `SIMULATION`: 409 `MODE_SIMULATION_NEEDS_FLAT` and the list by symbol, while the user holds a live reservation, a live open allocation or a SUBMITTED live attempt. Either way 409 `MODE_BRAKE_ON` under the brake. Each user changes only their own.
  - Moving to `LIVE` with simulated positions open succeeds (decision 26).
- **Evidence for E.2 (2026-10-30, the parent, inline):**
  - `ChangeMode` in `identity/application/`; `SqlAlchemyLiveExposure` in `execution/infrastructure/`; `holds_trade_capable_key` on the vault adapter. RED on assertions first (`404 == 409`, the old `/api/me` body), against a stub reader so the test module could import.
  - `/api/me` answers the stored mode, not the effective one: the panel says "forced by the brake" from the two values together.
  - `expires_at` is not read: a reservation the sweeper has not reached may still have a worker placing its order. A SUBMITTED attempt counts with or without an order id.
  - The reads run reservation, attempt, ledger, in the order exposure moves. Settling commits fills and terminal status together (TXN-B2), so whatever left one read has reached the next. The opposite order could read a user with a real position as flat; a test pins the order.
  - The lock test holds `FOR SHARE` with a reservation uncommitted, sees `not task.done()`, commits, and the change answers 409 naming the symbol.
  - Fourteen mutations seen red and restored: no row lock; ledger read first; the reservation's mode ignored, its user, or SUBMITTED; the attempt's mode ignored, its user, or a closing attempt missed; rehearsal fills counted; no market key; the key's user, activity, or trade capability ignored; the brake ignored. The attempt's user survived the first run, so the test that another user's exposure refuses nobody gained a SUBMITTED attempt.
  - Gate: ruff 0, mypy 0, full pytest with one test failing and nothing else: the secret sweep asks every new write route for a real body. It gained one and its file was rerun.
  - `frontend/src/shared/api/me.ts` still reads `dry_run` until E.7, so the panel on this branch is not deployable before then.
- [x] E.3 Adapters by mode (no behaviour change for a `LIVE` owner).
  - `exchange_for(session, user_id, mode)`: `LIVE` loads that user's vault key, `SIMULATION` returns that user's fake. The fakes exist whatever the brake. `LIVE` can never return a fake, nor `SIMULATION` a live adapter; a test pins each.
  - `FakeVenueBook` keyed by user, seeded only from `fake-fill-` rows. Two users in simulation on one symbol keep separate nets.
  - `tradable_pools` per mode; `venue_net_position_reader_for` takes the mode.
- **Evidence for E.3 (2026-10-30, the parent, inline):**
  - `ExchangesByMode` is the one place a mode becomes adapters; `SimulatedVenues` keeps one book and one set of fakes per user for the life of the process, because a fake holds its placed orders in memory and place and settle are separate jobs. `LIVE` handed a fake, or `SIMULATION` handed a live adapter, raises `InvariantViolation`; each direction has its own test.
  - A `LIVE` owner runs as before by construction: until E.4 and E.5 every job takes `job_mode`, which is `LIVE` with the brake off, and `tradable_by_mode[LIVE]` is the old set. Under the brake each user now has their own book, seeded from `fake-fill-` rows only. `net_positions_by_symbol` gained `rehearsal_only`; `distinct_users_for_pool` lost its last reader and went.
  - The fakes are built at startup whatever the brake, so the unrated warning and `log_simulated_exchange_startup` now run with the brake off too, with wording that still says "dry run". E.6 changes that wording.
  - `DryRunTradeCapability` did not go here: its replacement reads the mode in the pre-check, which is E.4's. The bullet moved there.
  - RED on assertions first, with two exceptions proven by mutation instead. `test_two_users_never_share_a_fake` passed at once against the stub, so "every user shares one set" proves it. The ledger test failed first on a `TypeError` for the new keyword, not on an assertion, so "the filter is dropped" and "a substring test instead of a prefix" prove it.
  - Ten mutations seen red and restored: a user's venues not kept; every user sharing one set; a book seeded from the first user's ledger; the wrong adapter not refused, in both directions and in each one alone; the modes swapped; an unknown owner getting a fake; the rehearsal filter dropped; a substring test instead of a prefix. The seeding mutation survived the first run, since the test only asked the first user; it now asks both.
  - Gate: ruff 0, mypy 0, full pytest with one test failing and nothing else (a first run was stopped by the machine's low memory): `test_booking_prepare_wiring.py` cuts `main.py`'s source at `async def exchange_for`, which is now `live_adapters_for`. The marker changed and its file was rerun.
- [x] E.4 An opening records its mode.
  - Done with E.1: `AllocateCapital` takes the user row `FOR SHARE` after the pool advisory lock and before the reservation write, computes the effective mode, and writes it on the reservation.
  - Done with E.1: `sum_active` counts only that mode (decision 26).
  - `DryRunTradeCapability` goes (moved from E.3): simulation needs no trade-capable key, LIVE does, for that exchange.
  - LIVE with no trade-capable key on that exchange refuses in the lock too, with the existing reason: a flip can land after the pre-checks. If the mode decided in the lock differs from the one the pre-checks used, nothing is reserved and the delivery runs again.
  - `PlaceOrder` picks its adapter from the reservation.
  - Lock-hold harness on real PostgreSQL: a flip to simulation waits for an opening in flight (`not task.done()`); an opening that starts after the flip runs in simulation; a real reservation never appears after the flat check passed.
- **Evidence for E.4 (2026-10-30, the parent, inline):**
  - Built in two steps so tests could fail on assertions rather than on constructors: first the plumbing with no behaviour (`AllocateCommand.pre_checked_mode`, `CurrentModePort`, `ModeExchangesPort`, `ReservationSnapshot.mode`, `for_job`), then the tests in red, then the logic.
  - One read per pass: `handle` and `open_now` each read the mode once, plainly, before any lock, and that read is what `pre_checked_mode` carries. A `FOR SHARE` there would invert the lock order. `AllocateCapital` compares its own in-lock read with it and raises `ModeChangedError`: nothing is reserved, no outcome is recorded, the rollback releases the lock and `WorkerRunner` runs the job again. It subclasses `DomainError`, and the only `except DomainError` in `src` wraps the balance read, which runs after this check.
  - `DryRunTradeCapability` is gone: `TradeCapability` moved to `shared/domain` with `key_refusal`, so the pre-check and the lock give the same code and text. The key is asked about only `if mode is Mode.LIVE`, before the lock and again inside it.
  - `open_now` gained the tradable check it never had, for the mode of that moment, and its refusal says the close executed. `tradable_pools` is now a map by mode in `ProcessDelivery`.
  - `PlaceOrder` asks `for_mode(reservation.mode)` after the expiry check. `ExchangesByMode.for_job` opens each mode the first time it is asked, once, and closes it with the job, so a simulated job decrypts nothing. `exchanges` stays only for `ClosePosition`, until E.5.
  - RED on assertions first, for every behaviour above. Two tests pass against the old code by nature and rest on mutations: the flip waiting for an opening in flight, and an opening after the flip.
  - Nineteen mutations seen red and restored: the mismatch check gone, or in one direction only; the key asked in simulation; the in-lock key refusal gone, or not recorded; the pre-check taking a row lock; the lock read taking none; the brake ignored; tradable always `LIVE` in `handle`, in `open_now` and in the refusal's text; the close note lost in `open_now` and in `_reject`; `pre_checked_mode` always `LIVE`; the pre-check asking the key in simulation; `PlaceOrder` always `LIVE`; every mode of a job opening `LIVE`; no reuse of a mode; the snapshot's mode as text. No survivors.
  - Gate: ruff 0, mypy 0, full pytest 0, after the last source change. Frontend not run, nothing there changed.
- [x] E.5 Everything after an opening follows the reservation.
  - `ClosePosition` reads the mode of the reservation it closes; `settle` learns it from the attempt's reservation before building its adapter; `CloseOrphans` per allocation. A job builds an adapter only once it knows the mode.
  - A REVERSE whose close and reopening differ in mode uses each one's adapter. Under the brake, a real allocation closes for real (decision 14), and a simulated position closes in simulation after the user went live (decision 26).
  - The tradable check for a close goes by the allocation's mode, not the user's: since E.4 `handle` asks the user's current mode for every signal, so a live user closing a simulated position on a simulation-only pool would be refused.
  - `exchanges` leaves `_build_process_delivery`. `job_mode` stays in `main.py` for the startup warning about unserved pools only, until E.6.
  - Added to this unit: the Existing-Position Guard compares a holding with the venue of its own mode. Comparing with one side would raise a false GHOST, an ERROR alert and a refusal, for a user who went live holding a simulated position, and the reverse under the brake.
- **Evidence for E.5 (2026-10-30, the parent, inline):**
  - One read, `AllocationModePort.mode_of(user_id, allocation_id)`, a plain read of the reservation scoped to its user; an allocation it cannot find raises instead of defaulting to a side. `ClosePosition`, `SettleExecution`, `HoldingGuard` and `handle` all use it.
  - `settle` asks after the not-SUBMITTED return, and a close with nothing recorded builds nothing. Asking the wrong side would answer "not found", and that releases a position that exists.
  - `HoldingGuard` splits the pool's holdings by allocation mode. Each mode has its own strategy net, pool net and venue read, so a long in one mode and a short in the other do not cancel out. A refusal in one mode closes nothing in the other. A flat market asks no mode.
  - `handle` goes by the allocation only when a close half exists with a reservation to read. An OPEN delivery goes by the user whatever the subscription's latest reservation ran in, and a close with nothing to close goes by the user and on to its own refusal.
  - `CloseOrphans` needed no change: it closes each allocation through `ClosePosition`.
  - `venue_readers_by_mode` hands the guard both registries. A real reader decrypts only if its pool is read, so a job on a simulated holding opens no key.
  - RED on assertions for every unit test. `test_a_reverse_closes_on_the_side_it_opened_on_and_reopens_on_the_users_side` runs both directions through the real `_build_process_delivery`, with the position opened by the flow and the user's side moved under it (going live, decision 26; the brake pulled, decision 14). It passed at once and rests on mutations.
  - Two existing tests were simulated positions seeded `LIVE`, which correctly went to a live side with no key; they now seed `SIMULATION`. The stubs in `test_main_job_owner_keys.py` never asked for a mode, so they now ask, and a job that asks for none signs nothing.
  - Eighteen mutations seen red and restored: the close and the settle always `LIVE` or always `SIMULATION`, in unit and through the flow; the settle asking before its status check; the guard on one venue, either way; holdings not split by mode; a refusal not winning; a mode asked for a flat market; the strategy net across modes; a close going by the user; an open going by the allocation; `mode_of` without its user filter, and taking a row lock; the readers swapped; the delivery job handing one side for both. "An open goes by the allocation" survived the first run, and `test_an_opening_goes_by_the_users_mode_whatever_its_last_allocation_ran_in` was added for it. No survivors.
  - Gate: ruff 0, mypy 0, full pytest 0, after the last change. Frontend not run, nothing there changed.
- [x] E.6 Reconciliation and the startup guard.
  - The scan and booking skip a simulated user with nothing real open, and compare only real fills with the venue, so a live user's leftover simulated position is no discrepancy. `/reconciliation/confirmed`'s `dry_run` reads true for such a user.
  - The startup guard as stated above, naming users by id and how many allocations each holds, and no longer refusing `DRY_RUN=true` with real allocations open.
  - The worker's log and alert wording stop saying one mode for the whole process.
- **Evidence for E.6 (2026-10-30, the parent, inline):**
  - The guard judges each open allocation and in-flight attempt against the mode its reservation recorded, so the brake has no say. MIXED offends whatever was recorded. `find_unclosable` refuses a real open allocation whose user has no active trade-capable key on its exchange, in any pool, enabled or not, and names the user by full id with the count per exchange. `assert_dry_run_matches_ledger` is now `assert_modes_match_ledger`.
  - `net_positions_by_symbol` takes a required `mode`: `SIMULATION` is the rehearsal prefix, `LIVE` its negation. There is no whole-pool read left. `ReadSymbolPositions` reads `LIVE`, so an allocation holding both counts its real fills only, and a discrepancy's allocation ids come from real fills too, which keeps simulated allocations out of booking.
  - `SqlAlchemyReconciledUsers` decides who is compared with the venue: mode `LIVE`, or `SqlAlchemyLiveExposure` not empty, or a discrepancy still open. **The third condition is the parent's decision, not in this task's text:** a venue position the ledger reads as flat is something real the exposure read cannot see, and only another scan can clear it, so scanning stops once it is clean rather than the moment the mode changes.
  - The filter runs before the key check, so a simulated user makes no warning noise. Both handlers stay under `if not settings.dry_run`. `/reconciliation/confirmed` is still admin-only and whole-system, and its `dry_run` is `settings.dry_run or` the signed-in admin is not reconciled. It takes `current_user` now, so a first visit creates the admin's row and a later one may mark them seen, as on every scoped route.
  - Wording: `_log_vault_self_test` lost its `dry_run` and speaks for both modes; a live opening is refused now, it no longer reserves and fails. The simulated-exchange lines stop saying "dry run". The unserved warning asks both sides and names each ("The live side (...)"), so a Pionex pool warns twice and a Bybit spot pool once. `job_mode` is gone.
  - RED on assertions: the guard's domain tests, the real-only read (it summed the simulated fills), the markets filter and its wiring, `/reconciliation/confirmed`'s `dry_run`, the unserved and simulated-exchange wording. The vault wording first failed on a `TypeError` for the removed argument; the signature went first and it was then seen red on `balance.sync`. **Two sets passed at once and rest on mutations:** `test_reconciled_users_integration.py`, whose class was written before its tests, against the strict order, and the reader's `test_each_row_carries_what_its_reservation_recorded`.
  - Thirty-seven mutations in `mutate_e6.ps1`, all killed and restored: mismatch judged by one fixed side, position and order, each way; mixed not refused; unclosable counting a simulated allocation, or matching the key by user only or exchange only; the guard ignoring either finding; a superseded or read-only key counting; the reader's mode and user constant; the real read inverted, widened or asked for the simulated book, and the simulated book seeded from real fills; reconciled ignoring its mode, exposure or discrepancy, a resolved or foreign discrepancy counting, `among` answering everyone; the filter dropped or asked after the key; either handler ignoring it; confirmed ignoring the brake or the user, or not handing it on; one side of the unserved warning, or the wrong name. Two wiring asserts were added before the run so the handler and wrong-name mutations had something to fail: `pool_set.by_key, active, reconciled, warn=...` in each handler, and both side names in the Pionex test.
  - Gate: ruff 0, mypy 0, full pytest with one test failing and nothing else: `test_main_pool_reload.py` cuts `main.py`'s source at `tradable_pools`, the line this unit removed. The marker changed to `simulated_venues = SimulatedVenues(` and its file was rerun, green. Frontend not run, nothing there changed.
  - **Deploy risk for E.8:** the new guard refuses to start the worker on any real open allocation whose user has no active trade-capable key on that exchange. The Pionex key is off and the Bybit key was deleted on 2026-10-21, so an old open real allocation on either, a stranded Pionex position for instance, would stop the worker at deploy. The rehearsal on the restored backup must run this exact check before production restarts.
- [x] E.7 The panel (EN/ES).
  - The badge reads `/api/me`: Simulation or Live for this user, clickable, with a confirmation; moving to Live says real orders will be placed. With the brake on it shows that simulation is forced for everyone and cannot be clicked. Each 409 is shown in words, and the flat refusal lists the symbols.
  - Discrepancies and the nav badge read the per-user value.
- **Evidence for E.7 (2026-10-30, the parent, inline):**
  - `DryRunBadge` is now `ModeBadge`, with `ModeDialog` beside it. The brake on shows "Simulation forced" as a plain status with its sentence as a title, whatever the user's own mode; off, "Simulation" in amber or "Live" in the gain colour are buttons. A pending or failed read stays neutral and cannot be clicked, as before.
  - The dialog keeps `DeleteKeyDialog`'s safeguards: the click that opens it sends nothing, `Cancel` has the focus, and nothing closes it in flight. It stands apart from the badge, so a `MODE_BRAKE_ON` refusal stays on screen after the read it triggered has turned the button into the forced badge. The words are the panel's own, never the server's.
  - `useChangeMode` reads `me` again and waits for it on every settled attempt but a 401, and invalidates `/reconciliation/confirmed`, whose `dry_run` follows the mode. `useMe` refreshes every minute, the freshness the old badge had from `/health`, so a brake pulled under an open page reaches the badge.
  - Discrepancies and the nav badge needed no code: they already read `dry_run` from `/reconciliation/confirmed`, which E.6 made per user. Only the page's sentence changed, since "dry run" no longer covers why nothing is compared. The two Settings warnings that said "with dry run off" now say "in live mode".
  - **A behaviour that moved:** the badge used to show the mode while signed out, because `/health` needs no sign-in. A mode belongs to a user now, so a signed-out page says "Mode unknown". `shared/api/health.ts` had no reader left and went; the `/health` route stays as it is, and `stubApi` still answers it.
  - The rehearsal labels of positions and trades ("Dry run") are separate keys and were left alone: this task names the badge.
  - RED on assertions: 22 tests failed against a minimal badge and a stub `changeMode`, never on an import. Twenty-seven mutations in `mutate_e7.ps1`, all killed and restored in the end. Two survived the first run and were rerun alone in `mutate_e7b.ps1` after the fix. "Any status read as a refusal" was a real hole, closed by a test of a 500 naming a refusal. "The click sends" sat in `showModal`, which jsdom lacks, so it proved nothing; moved to a line that runs, it was killed.
  - Gate: `npm run lint` 0, full `vitest run` 106 files and 2949 tests, both on the final tree. Backend not run: nothing there changed. **Not seen in a browser:** `vite.fixture.config.ts` does not answer `/api/me`, so the badge and the dialog have only been checked by tests. The owner looks at both after the deploy.
- [x] E.8 Rehearsal and deploy (owner-run): a fresh backup; 0035 rehearsed on a throwaway restore with a downgrade to 0034 and a second upgrade, checking every reservation's mode against its fills and that the owner is `LIVE`; both services stopped for the migration, away from a 4h candle close; pps.6. Every query a script runs is exercised locally first.
  - **Prepared, not run (2026-10-30):** `rehearse_0035.sh` and `deploy_0035.sh` in the session scratchpad, driven locally by `rehearse_local_0035.py`, `LOCAL RESULT: ok`. Three scenarios on a copy of the dev database at 0034, seeded with a real open, a simulated open, a closed mixed and an empty reservation: one user with a key passes both, downgrade included; the key gone, the rehearsal stops at 0034 with nothing written and the deploy stops at 0035 with the services stopped; a second user, the rehearsal passes and the downgrade is refused. The guard's first local run refused a seeded closed allocation on a coin-m symbol that `base_currency_of` cannot split: that is the guard's stated rule, and the seed moved to `BTCUSDT`.
  - `backend/scripts/check_mode_guard.py` runs the worker's own guard, so the check on the restored backup is the check that decides, not a second reading of "open". The rehearsal runs it on the copy before production is touched, and the deploy runs it again after migrating.
  - The deploy adds two things the task does not name: a backup taken with both services stopped, since the rehearsal's is minutes old by then, and a refusal to start within 5 minutes after or 15 before a 4h close. `deploy_0035.sh` carries a placeholder for the merge commit. A failed migration or a refusal after stopping leaves both services stopped: the pulled code needs 0035, and old code cannot write `reservations.mode`.
  - The panel goes after the API here, unlike a panel-only deploy: the new bundle refuses an `/api/me` without `mode`.
- [x] E.D Gate, independent verifier, then push and PR on the owner's word, merge, deploy, delivery log.

### Independent verification (2026-10-30)

An Opus verifier read head `a4f42a6` against `ddf8262`. **No blockers.** E.1 to E.7 pass, and so do E.8's scripts. Its probes ran on real PostgreSQL: the migration's cases, and an opening queued on the pool lock while a flip lands, which raises `ModeChangedError` and reserves nothing. Not checked: the panel in a browser, the VPS branch of the scripts, production's data, and a signal through `build_worker_runner` in simulation with the brake off.

Closed after the report:
- **A4, a mode change left no line.** `ChangeMode` now logs at INFO after the commit, naming the user and the mode: it decides where the user's next signal goes. RED on an assertion, four mutations killed. A first version logged at WARNING on the belief that the API configures no logging; `shared/infrastructure/api_logging.py` shows it does, and INFO is where a changed share and a deleted strategy already go.
- **A2, a closed allocation with real and rehearsal fills.** The guard reads it flat, but the scan now counts real fills alone, so it reads as a position to compare with the venue. It needs both kinds on one allocation, which production may not hold. `rehearse_0035.sh` counts them and ends with a REVIEW line when any exist.
- **A9, the deploy's edges.** A failed backup now stops with the state in words. A guard refusal starts the API, so a webhook is not lost, and leaves the worker stopped. A service that is not active ends in `STOP`, never in `done`.

Recorded, not changed:
- **A1.** 0035's "open" nets quantity alone, while the guard also subtracts base-currency fees and calls an unsplittable symbol open. Both failures are loud, and the rehearsal meets either before production.
- **A3.** A symbol `base_currency_of` cannot split reads open for ever, so it blocks going to simulation and counts as unclosable. It is the guard's stated rule; production's symbols split.
- **A5, close before PR F or PR G.** `/reconciliation/confirmed` is whole-system for the admin, but `dry_run` comes from the admin alone, so an admin in simulation with nothing real sees nothing of another user's discrepancies. The Telegram reminder remains. E.6 asks for this value, and it has no reach while the owner is the only user.
- **A6, close before PR F.** Saving a read-only key does not check exposure, so a user holding a real position can supersede their key, and `find_unclosable` then refuses the next start for everyone.
- **A7.** A `LIVE` `PENDING` reservation retried inside its 30s TTL after a restart places for real under the brake. Line 1118 says the order follows the reservation, so this is by the rule, though decision 14 reads narrower.
- **A8.** The in-lock key refusal on a reverse continuation omits the "close executed" note the pre-lock refusal carries.
- **Deploy window.** E.2 renamed `dry_run` on `/api/me`, and the old bundle requires it, so between the restart and pps.6 a fresh load shows the signed-out gate. The other order is worse: the new bundle refuses the old answer. pps.6 follows the deploy at once.

### PR E's delivery

PR #91 merged 2026-10-31 15:59 UTC as `c9b7ec08164e`, with a merge commit. No dependency changed.

**PR E's deploy, 2026-10-31** (owner-run):
1. Pull as `strategy` to `c9b7ec08164e`, then `rehearse_0035.sh` on a fresh backup, `/root/sm_pre0035_20261031_1626.dump`. Whole output read: production at 0034 with one user and no user without a trade-capable key; the copy's counts equal production's (15 reservations, 119 ledger entries, 58 signals, 58 deliveries); ledger ids and `xmin`, and every column 0035 does not own, unchanged after the upgrade, the downgrade and the second upgrade; `LIVE FILLED 9`, `SIMULATION FILLED 6`, each agreeing with its fills and orders, and the same modes again on the second upgrade; guard exit 0 with no open allocation; closed allocations holding both real and rehearsal fills: 0, so no REVIEW line.
2. pps.6 built before the deploy, so that only the link was left to move after the restart: the owner built `c9b7ec08164e`, SHA-256 `12d6fb021aeed2186ec960a52e5bffa5259839fc8e2e1fcba90b1c115f46aafb`, and the copy reached 100%.
3. `deploy_0035.sh`, 33 minutes into the 4h candle, 2026-10-31 16:33 UTC. Both services stopped, backup `/root/sm_pre0035_deploy_20261031_1633.dump`, 0034 to 0035. Six scheduled jobs stayed `PENDING`, none of them a signal's. Every existing user reads `LIVE`. Reservations: `LIVE FILLED 9`, `SIMULATION FILLED 6`. Guard: no open allocation, one trade-capable key, exit 0. Both services active, and the webhook answers 401 with no secret.
4. pps.6's VPS block: `/root/panel-c9b7ec08164e.tgz: OK`, `readable`, `bundle:   c9b7ec08164e`, `checkout: c9b7ec08164e`.
5. The panel, read by the owner: "Todo ok". The badge and the dialog have now been seen in a browser. The handover said to cancel the dialog, not confirm it, so `POST /api/me/mode` is not known to have run in production.

**Read from that output:**
- The API read `failed`, not `inactive`, right after `systemctl stop`. Read from production with `check_api_stop.sh`: `code=exited, status=143/n/a`, `Failed with result 'exit-code'`, no exception in the window, `SuccessExitStatus=` empty, `NRestarts=0`. 143 is 128 + 15, the SIGTERM the stop itself sends, and an exit code that systemd is not told is a success reads as a failure. Not a defect, and the unit stays as it is: no earlier deploy script printed the state after a stop, so this was never seen rather than new.
- The deploy's "WARNING/ERROR lines" listed two INFO lines: its `grep` matches " ERROR " inside the text of `operator alerts are on: ERROR and above are forwarded`. It found no real warning or error. The list was noise, not a finding.
- `open allocations: {}` means the ledger holds no open position, so the SFP opening of 2026-10-30 had already closed by the deploy.

**The first signal after PR D (read by the owner, 2026-10-31):** `SFPUSDT.P` sell received 2026-10-31 01:10:03 UTC, position size 0, after PR D's and PR D2's deploys: one ACTIVE subscription, one delivery `PROCESSED`. The opening's allocation went from 12 fills to 25, so 13 closing fills, and it nets to zero. An accepted signal passed ingress, which by then authenticates only by the strategy's hash, with the alert's URL unchanged. This closes the check left open under PR D2's delivery, for a close's delivery too.

## PR E2: what must close before PR F

Branch `fix/multi-user-before-public-list`, cut from `main` at `c9b7ec0`; it carries PR E's delivery record. No migration. The owner's word, 2026-10-31: "Dale, arrancá con los cuatro".

- [x] E2.1 A5: the `dry_run` of `/reconciliation/confirmed` is whole-system, as the route is. True only under the brake, or when the scan reconciles nobody.
  - `SqlAlchemyReconciledUsers.anyone()` applies the same three conditions over every user. The first version asked user by user; `test_the_statement_count_is_the_same_for_one_and_for_twenty_open_discrepancies` caught one statement more, and the route is polled every 60 s per tab, so it now takes a fixed number of statements. `SqlAlchemyLiveExposure` gained `symbols_of_everyone()` rather than a second definition of "real", and `symbols(user_id)` keeps a required argument, so a caller of the flat check cannot read everyone's by forgetting the user.
  - The route no longer depends on `current_user`: the router's `require_admin` is what guards it, and the reader's identity no longer decides anything.
  - RED on three assertions before the fix, two on the route and one on `anyone()` with a stub returning False. Eleven mutations in `mutate_a5.ps1`, all killed and restored. `users` outlives the fixtures' truncates, so tests over every user use the new `nobody_is_live` fixture, which restores each mode afterwards.
- [x] E2.2 N1 and N5: an opening reads the subscription inside the pool lock `Leave` takes, and one that is not `ACTIVE` reserves nothing. Proved on real PostgreSQL with the lock-hold harness, in both orders.
  - `AllocateCapital` asks the new `DeliverySubscriptionPort` after the policy re-check, inside the lock. Anything but `ACTIVE` skips with `SUBSCRIPTION_NOT_ACTIVE`, on the delivery (`REJECTED`), logged at INFO because leaving is the user's own action. A delivery with no subscription is an `InvariantViolation`, not a skip. N5 is the same check: an `ENDED` subscription and a `LEAVING` one are refused by one read.
  - A retry that finds its reservation returns before the lock and never asks: a reservation made before the user left carries its opening to the end. Leaving stops openings that have not reserved, no others.
  - Tests: `test_allocate_capital_left_subscription.py`, `test_delivery_subscription_integration.py`, `test_leave_vs_opening_concurrency.py` (both orders, real adapter and recorder, the second actor seen waiting), and one through the real worker wiring in `test_simulated_fill_webhook_to_ledger.py`. RED on assertions, except `test_a_resumed_reservation_never_asks`, whose first RED was the rig (the fake held no existing reservation), so its evidence is the mutation.
  - Ten mutations in `mutate_n1.ps1`, all killed and restored, the wiring in `main.py` and the read before the lock among them. The first run reported two mutations as not found: a script error, fixed and rerun, not a pass.
  - The full gate found one seed in `test_continuation_outcomes_integration.py` that hosted a delivery on an `ENDED` subscription, a state that cannot open any more. The seed now subscribes first; the test's assertions are unchanged.
- [x] E2.3 N2: a `LEAVING` subscription left with nothing, because its reservation was released unfilled, ends. PR F's Subscribe/Leave puts this within any user's reach.
  - `reservation.sweep` now runs `EndFlatLeaving` after the expiry and before its successor, so one place covers every unfilled path (released by a settle, expired by the sweeper) and an expiry ends its subscription in the same run. The delay is one sweep, 60 s by default. Each decision is the existing `end_if_flat` under the user's pool lock, and a commit after each gives that lock back, so the sweep holds one at a time.
  - Found while writing it, and fixed in the same unit because the sweep would have reached it every minute: `holds_open_allocation` read an expired reservation as nothing held. The sweeper expires a `SUBMITTED` reservation at its TTL while its order may still fill, and fan-out sends a close to `ACTIVE` and `LEAVING` holders only, so ending there strands a position. `Leave` already had the same defect, by the user's own click. An opening attempt in `SUBMITTED` now counts as holding, whatever its reservation says.
  - The same method read the ledger first. An opening's settle takes no pool lock, so one committing between the reads left the fill unseen and the reservation gone, and a holder read as flat. It now reads reservation, attempt, ledger, the order `SqlAlchemyLiveExposure` documents.
  - Tests: `test_end_flat_leaving.py`, `test_end_flat_leaving_integration.py` (pool lock seen waited for, the settle racing the ledger read, with the reservation live and with it expired; the second was added after the verifier showed the first alone proves only that the ledger is not read first), two in `test_sweep_handler.py`, and one through the real worker wiring in `test_simulated_fill_webhook_to_ledger.py`. RED on assertions against empty skeletons. `seeds.open_allocation` now seeds its attempt `FILLED`: it books a fill, so `SUBMITTED` was a state production cannot reach.
  - Fifteen mutations in `mutate_n2.ps1`, all killed and restored, the wiring in `main.py` and the ledger read first among them.
- [x] E2.4 A6: `SaveCredential` refuses a key that cannot trade while the user holds something real on that exchange, read inside the pool lock and after the venue call, as `DeleteCredential` does. The panel shows the refusal in words.
  - New outcome `EXCHANGE_HOLDS_REAL_EXPOSURE`, a 409 naming the symbols. After `evaluate_key`, a key that cannot trade takes the user's pool lock, reads real exposure on that exchange, and stores inside the same lock, so an opening either committed before the read or finds this key when it takes the lock. A key that can trade skips the step: nothing it supersedes leaves a position without a key.
  - "Real" stays one definition: `SqlAlchemyLiveExposure.symbols_on(user_id, exchange)`. A simulated reservation refuses nothing, because closing it needs no key. The script path (`credential_cli.py`) carries the same lock and read and its own guidance line.
  - Panel: `holdsRealExposure` in `credentials.ts`, EN and ES copy (usted), the secret test's list of endings.
  - Tests: six in `test_save_credential.py`, `test_save_key_over_real_exposure_integration.py` (each kind of exposure, each kind on another exchange, another user, the route's own wiring, the save seen waiting for an opening that holds the lock), one on the 409 in `test_credentials_router.py`, one source pin for the script. RED on assertions against skeletons. Fourteen mutations in `mutate_a6.ps1`, all killed and restored, after adding the tests that the wiring and the per-exchange filters did not have yet.
- [x] E2.D Gate, independent verifier (E2.2 is concurrency and E2.4 a guard), then push and PR on the owner's word, merge, deploy (pull, restart both services away from a 4h close, pps.6), delivery log.
  - Independent verifier (Opus, 2026-10-31, `c9b7ec0..e74b117`): E2.1 to E2.4 met, no blockers. It traced the lock order through sweep, `Leave`, allocate, closing settle, archive and save, and a probe with a raise midway kept the earlier ending, left the failing item `LEAVING` and freed that user's lock.

### PR E2's advisories

- A1, closed: the attempt-before-ledger order was not pinned. Regression test added from the verifier's probe, mutation in `mutate_a1.ps1` killed.
- A2, accepted: `holds_open_allocation` has a fourth caller, the archive refusal's `held_by`. An order in flight under an expired reservation now names its holder there, where it refused with nobody named. Still a refusal, and a truer one; pinned by a test. Stale docstrings fixed.
- A3, open: fan-out's `_holds` reads no attempt. A close arriving while an opening order is in flight under an expired reservation reaches nobody, and the fill that lands later is a position nothing closes. Already there at `c9b7ec0`, and not fixed by adding the read: there is no fill yet for that close to act on. It needs its own design, a close that waits for the opening as the open-after-close continuation does the other way round. The docstring now says so.
- A4, recorded: an opening attempt stuck `SUBMITTED` keeps a subscription `LEAVING` with no line from the sweep; the watchdog reports the exhausted job, not the subscription. A skip in `open_now` does not carry decision 26's "close half executed" wording, as every other `AllocateCapital` skip at the base. `find_unclosable` goes by recorded mode and `_open` by `holds_live_fill`: they differ only for a `LIVE` reservation holding only rehearsal fills. The refusal detail that claimed "the key that closes it stays" was false for a user with no key that trades, and was reworded.
- Not checked by the verifier: `vault_saver` end to end (its session factory binds the dev database, so the script's wiring has only a source pin), and multi-worker concurrency, which it reasoned about because `WorkerRunner` is one loop. The counts of mutations and the RED claims above come from scripts in the session scratchpad, not in the repository.

### PR E2's delivery

PR #92 merged 2026-10-31 19:45 UTC as `44099dd99af1`, with a merge commit. No migration, no dependency changed, 65 files, six of them in `frontend/`.

**PR E2's deploy, 2026-11-01** (owner-run):
1. pps.6 built before the deploy: `44099dd99af1`, SHA-256 `5928dd5e6561c419708aa621d669984d5a9653a99deb487e79d80874f0d56a55`, copied to the VPS.
2. `deploy_e2.sh`, 100 minutes into the 4h candle, 2026-11-01 01:40 UTC (the script's own time, `02:40:31`, is the VPS's clock, one hour ahead). Alembic `0035` before and after. Subscriptions before: `ACTIVE 3`, `ENDED 3`. Fast-forward `c9b7ec0..44099dd`, checkout `44099dd99af1`. Both services active, the webhook answers 401 with no secret, one live `reservation.sweep`, and no WARNING or ERROR line since the restart. That grep now leaves out the alert line that was noise at PR E.
3. pps.6's VPS block: `/root/panel-44099dd99af1.tgz: OK`, `readable`, `bundle:   44099dd99af1`, `checkout: 44099dd99af1`.

**Not seen in production:** none of the four behaviours has run there. Production has no `LEAVING` subscription, so the sweep's new step has nothing to end; nobody saved a read-only key, and sealing one is forbidden, so the refusal and its panel copy stay proven by tests only; and no signal has arrived since the deploy, so the first opening is the first run of the read inside the lock.

## PR F: the author's name, the public list, the admin's users list

Branch `feat/multi-user-public-list`, cut from `main` at `44099dd`; it carries PR E2's delivery record. Migration 0036. Planned from the code at `44099dd` and decisions 27 to 30, taken 2026-11-01. What had to close before PR F (N1, N2, N5, A5, A6) closed in PR E2. The signals' `status`, `outcome_reason`, `outcome_detail` and `decided_at` stay, because they hold the strategy-level refusals (C.7).

**What the code has today:**
- Every strategy read is scoped to its author. No route shows a `PUBLIC` strategy to anyone else, and only `Subscribe` and `UpdateStrategy` read `visibility`.
- `POST /api/subscriptions`, `POST /{id}/leave` and `PATCH /{id}` are open to any signed-in user. The panel only calls the PATCH.
- `SignInGate` renders the shell for the admin only.
- Nothing computes a round trip from signals. An opening or a closing is not stored: `PositionTransition.classify` derives it from `position_size`, and `find_prior` walks one (strategy, exact symbol) by `received_at`, whatever the status.
- `users.last_seen_at` exists, and its docstring names this list as its reader. Key coverage is readable from the API (`read_key_coverage`); a key that does not open or a failing balance sync is known to the worker alone.

**Decided in planning, not asked of the owner:**
- A strategy is on the public list and has a public page when it is `PUBLIC`, not archived, and its author has a name. Otherwise the public page answers 404 to everyone, its author included, who has their own page.
- Age is `strategies.created_at`.
- Someone trades live when their subscription is `ACTIVE` and their effective mode is `LIVE`. `LEAVING` opens nothing, so it does not count. Under the brake the live count is 0 and the capital is absent.
- The record, per (strategy, symbol), over every stored signal in the order of `find_prior`:
  - from flat, a nonzero `position_size` opens at that signal's price, and its sign is the side;
  - to zero, it closes;
  - a sign flip closes and opens at the same price, so one closed trade and a new open;
  - a change that keeps the sign, and zero to zero, are skipped and leave the entry as it is. `classify` raises on them; a public read does not;
  - a long returns `exit / entry - 1`, a short `1 - exit / entry`;
  - an open trade counts for nothing.
- `SignInGate` stays until PR G. Access is the door and this is the second lock, and it should open with the readiness work, not before it. PR F's pages for other users are tested at component level, and the admin reads them in the panel.
- The admin list's "degraded" means what the database can say: an enabled pool with no active key. It is labelled so. Last sign-in is `last_seen_at`, at most a minute stale. Open positions come from `open_allocations(None)` and its fold, not from a count that only approximates them.
- A name is 3 to 30 characters once trimmed, holds no `@`, and is unique on `lower()`. It can change, and it cannot be emptied, because a `PUBLIC` strategy rests on it.

- [x] F.1 The display name, backend (decision 27). 0036 adds `users.display_name`, nullable, with its check and its unique index on `lower()`. `PUT /api/me/display-name` answers 200, 409 `DISPLAY_NAME_TAKEN`, or 422. `/api/me` returns it. `RegisterStrategy` and `UpdateStrategy` refuse turning public with no name, 409 `AUTHOR_HAS_NO_DISPLAY_NAME`. A strategy already `PUBLIC` with an unnamed author is not refused anything: its other settings can be edited. The route joins both sweeps.
  - `normalize_display_name` also folds compatibility forms (NFKC) and refuses invisible characters, beyond the plan: `A<zero-width>na` reads as `Ana` and passes a unique index, so it would let someone pass as another author. Letters that only look alike across alphabets are not caught.
  - The index decides a taken name, not a read first, so two users racing for one leave one holder, proved through the route. The refusal names nobody.
  - `AuthorNamesPort` is a required argument of both use cases, so a caller cannot forget it. Thirteen test call sites took `FixedAuthorNames`.
  - RED on assertions against empty skeletons. Forty-one mutations in `mutate_f1.ps1`, all killed and restored, eight of them on the migration, whose RED comes from them. The full gate found `test_0029_users.py` pinning the table's columns; it now lists the name.
- [x] F.2 The display name, panel. A form in Settings, the header shows the name and the e-mail until there is one (decision 17), and the visibility control shows the refusal in words. EN and ES (usted). Done: `DisplayNameSection` on Settings, `chooseDisplayName` and `useChooseDisplayName` in `shared/api/me.ts`, the name in `TopBar`, `AUTHOR_HAS_NO_DISPLAY_NAME` in words in `VisibilityControl` and `NewStrategyDialog`. A missing or odd `display_name` reads as no name and never refuses `/api/me`, so a panel ahead of the API locks nobody out. The owner's review of the running page (2026-11-01): the form sits in `ReportSection` under an h2 `Profile` outside the frame, as `Exchange keys` sits outside its cards, the field takes all the width its button leaves, the explanations of both sections open from an `InfoButton` beside their h2, and the top bar's name reads as `text-sm font-medium text-ink`, no longer a caption. The first version said "saved" only to a screen reader, since a neutral `InlineStatus` is `sr-only`; the button now says it, as `PoolShareEditor` does. That region is the name section's own, beside the page's region for keys, which `SettingsPage.test.tsx` now reads apart, and "every button disabled during a key save" is now scoped to the keys: an information button is never disabled, and the name races nothing there. The page gains `GET /me`, which in the running panel shares the top bar's cache and adds no request. RED on assertions, 44 mutations killed (two survived the first run and each got a test), lint green, 3000 frontend tests green. The section draws only once `/api/me` answers: `vite.fixture.config.ts` passes that route through to the API on :8000.
- [x] F.3 The public record, pure domain: `performance/domain/public_record.py` builds closed trades from a strategy's signals by the rules above and adds them up by decision 28. Trades of one UTC day are summed and `compound` does the rest. `daily_returns` is bound to `ClosedTrade`, so it is not reused as it stands. Each rule gets its test, REVERSE and the skipped changes included, and a symbol in each spelling keeps its own chain, as `find_prior` does.
  - `RecordSignal` is the module's own type, so `performance/domain` imports nothing of `signals`. `closed_trades` and `build_public_record` are what F.4 calls, once per strategy, with every stored signal of it whatever its status.
  - `curve.py` gains `sum_by_day`, the UTC-day sum and its refusal of a naive datetime, and `daily_returns` now calls it, so the panel's curve and the public record share one rule. No change to `daily_returns`' behaviour: `test_curve.py` passes untouched.
  - A zero entry needs no guard: `ck_signals_price_positive` and the alert's own parse keep a stored price positive.
  - A record with nothing closed answers 0 trades and 0 return. Whether that reads as "0 %" or "no record yet" is F.6's.
  - Two signals of one symbol with the same `received_at` are read in the order given, so F.4 orders its read by `received_at, id` to stay deterministic. `find_prior` is strict, and would call neither the prior of the other.
  - 29 tests. RED on assertions against an empty skeleton, for the 25 that could fail there; the rest are proven by mutations. Twenty-three mutations in `mutate_f3.ps1`, all killed and restored, three of them on `curve.py`. Full gate green.
- [x] F.4 Public reads. `GET /api/public/strategies` and `GET /api/public/strategies/{id}`: name, author's name, exchange, venue, settlement currency, age, closed trades, return (labelled unleveraged and before fees), live count, capital (decision 30). A new cross-user read port, in `performance/application` with no import from the ledger. The statement count is the same for one strategy and for twenty, as in E2.1. A body is an explicit list, so no `author_id`, e-mail, secret hint or subscriber row can reach it, and a test pins that. Both routes join both sweeps. Cross-user: B gets 404 on A's `PRIVATE` strategy, on an archived one, and on one with an unnamed author, and no row changes.
  - `PublicStrategiesSourcePort` takes no user, and `_LISTED` in its adapter is the one definition of the list, so `listing` cannot reach a strategy `listings` leaves out. Each method selects named columns: the e-mail, the secret's columns and `raw_payload` are in no statement.
  - The wire names the two limits itself: `unleveraged_return_before_fees`, a `Ratio`. `created_at` is the age, `closed_trade_count` the closed trades, `live_subscribers` the live count, and `capital` is a `Money` in `settlement_currency`, null under the brake and `"0"` with the brake off and nobody live. The body also carries `id`, which the plan does not list and the public page needs.
  - `performance/domain/public_capital.py` adds each seat with `requested_from_percent`, so the figure rounds down and reads the pool's total as an opening does, never `available`. A seat whose pool has no balance read still counts as someone live, and adds no money.
  - One 404, "no such strategy", for private, archived, unnamed author and unknown id, to its own author as well. The list runs oldest first, the id breaking a tie.
  - Both routes read through `get_snapshot_session`, so the four statements are one read-only `REPEATABLE READ` snapshot: the `SET`, the listings, the signals, the seats. Three under the brake. The count is pinned for one strategy and for twenty, and the page issues the same four.
  - In the sign-in sweep the two routes sit in `SCOPED_TO_THE_SIGNED_IN_USER` with a comment, since they answer no user's own rows. The secret sweep seeds a public strategy of a named author, and asserts the routes carry not even the last four.
  - The read loads every stored signal of every listed strategy on each request, and nothing caches it. Its cost at volume was not measured; look at it again once the list holds strangers' strategies.
  - 39 tests. RED on assertions against empty skeletons, and on `[strategy] = ...` where a test unpacks one row. Forty-one mutations in `mutate_f4.ps1`: 40 killed, and W09 (no router-level `current_user`) is equivalent, since `get_snapshot_session` requires it too; W13, which removes both, dies. The first run left S08, S17 and S18 alive: the two "its own strategy" tests read one page, where a filing under the first id asked about cannot show, so they now read the list; and the signal tiebreak test could pass by luck, because the table's order depends on the plan, so its close is now first by both storage and idempotency key. S08 then died three runs of three.
- [x] F.5 The author's total: `subscribers` and `live_subscribers` on `GET /api/strategies`, scoped as that route is (decision 10).
  - `StrategySubscribersAdapter.counts` reads both numbers in one statement, `ANY` over the ids, and only those ids: the route has already narrowed them to the reader's own strategies, so the counts cross users on a strategy its reader authored and nowhere else. The answer is two integers, with no e-mail, name or amount.
  - `subscribers` is everyone with an `ACTIVE` subscription, the author and simulated subscribers included. `LEAVING` counts for neither number: it opens nothing, the rule the public list already follows, so `live_subscribers` never exceeds `subscribers`. The author counts only while they hold a subscription, which is what decision 30's sum does and how the owner described it: "un suscriptor (el autor)".
  - `live_subscribers` is those in `LIVE`, and 0 under the brake, with the total unchanged. The brake is applied in the router's `_subscriber_counts`, never in the statement.
  - The same rule is now read in two statements, this one and `live_seats` of F.4, because `strategies` cannot import `performance`. A test compares the two answers for one strategy, with a leaving and a simulated subscriber beside the live ones, with the brake on and off.
  - The fields sit on `StrategyView`, so the detail, the writes and the register answer carry them too, beyond the route the plan names. Each of those reads one more statement; the list reads one more in total, whatever its length.
  - 14 tests in `test_strategy_view_subscribers.py`. RED on assertions against an empty skeleton for 9; the rest are proven by mutations aimed at each test alone. Nineteen mutations in `mutate_f5.ps1`, all killed and restored. Full gate green.
- [x] F.6 The panel's strategies: "My subscriptions", "Explore" and "Authored" (AD11), the public page, and Subscribe and Leave with a share. The subscribe step says the capital joins a public sum (decision 30). With no key on that exchange a user can browse and not subscribe (decision 13), and the refusal is in words. EN and ES (usted).
  - Three backend gaps the plan missed, closed here because the pages could not stand without them. `Subscribe` accepted a pool whose key was deleted (a deleted key disables the pool and keeps the row), so decision 13 held only for a user who never had a key: it now needs an enabled pool, and an author's registration keeps the wider read. `GET /api/subscriptions` names no strategy and a strategy turned private leaves the public list, so `GET /api/subscriptions/held` answers the live rows with the strategy's name, author and market; an ended row is left out, so nobody who left reads a later name. The share preview was the author's alone: it now reaches anyone who may subscribe and anyone holding a live subscription, and a stranger with no pool there gets a 404 with no ERROR line, which would have reached Telegram. The preview always reads the user's subscription now, so its statement test reads 3 in both cases.
  - No keyed-exchanges list on `/api/me`, against AD11 and the note under PR F's plan: an enabled pool on the strategy's exact market answers the question more precisely, and `usePools` already holds it.
  - `/strategies` now lands on My subscriptions; Authored moved to `/strategies/authored`, and its back link and the delete's redirect with it. A layout route holds the heading and the three tabs. The public page sits outside it, at `/strategies/explore/:strategyId`. `/strategies`, Explore and the public page are not exchange-scoped; `/strategies/authored` and the detail are.
  - A subscription is managed in My subscriptions alone, because a strategy turned private has no public page. Its link goes to the public page, which says "not on the public list" without a further request.
  - `useShareDraft` is extracted from `PoolShareEditor`, so the subscribe form and the editor read one rule for the text, the handle and the served amount. The editor takes only `id`, `subscription` and `archived_at`.
  - A return shows a dash until a trade has closed. A capital of "0" reads 0.00 and is told apart from an absent one.
  - `SignInGate` still admits only the admin, so what a stranger sees is tested at component level. The running pages were read in Edge on `strategy_manager_review`, seeded with three authors, at desktop and narrow width. Capital was not seen running: `DEV_USER_EMAIL` with the brake off refuses to start, so a local panel shows the brake's dash, and the figure is pinned by component tests and F.4's router tests.
  - A real server answered subscribe 201, leave 200 and a deleted key 409 `NO_POOL_FOR_MARKET`.
  - Mutations: 22 of `mutate_f6a.ps1` plus 6 aimed at each backend test that passed at once, and 75 of `mutate_f6b.ps1` on the panel, all killed and restored. Two panel survivors showed tests that read "nothing was sent" before a mutation could send; those tests now wait a turn of the event loop first. Full gates green.
- [x] F.7 The admin's users list (decision 8). `admin/application`, `GET /api/admin/users` under `require_admin`: e-mail, name, mode, exchanges with a key and whether any is degraded, subscriptions, open positions, last seen. No amounts and no performance, pinned by a test. The statement count does not grow per user. Panel page, and Discrepancies and Users show only when `is_admin` (AD11).
  - Five statements in one read-only snapshot, however many users there are: the snapshot, `everyone`, `read_key_coverage`, `live_counts_by_user` and `open_allocations()`. The last two facts come from the readers the worker and the panel already use, so "degraded" and "open" cannot drift from them.
  - `exchanges_with_no_key` is the plan's "degraded": an enabled pool with no active key. A deleted key disables its pool, so it shows in neither list. The panel labels the line "Enabled pool with no active key".
  - `subscriptions` counts `ACTIVE` and `LEAVING`, what `GET /api/subscriptions/held` lists, the author's own included. `open_positions` is one per open allocation, so it matches the rows of that user's open positions, and orders in flight do not count.
  - The mode is the one the user chose, not the effective one. Under the brake the page says everyone trades in simulation whatever it shows.
  - The list is ordered by e-mail and has no pagination, which is fine for a closed panel. Worth another look if sign-up brings many users.
  - `AdminRoute`, beyond the plan: anyone else meets "not found" at `/discrepancies` and `/users` and neither page asks for its data. `SignInGate` hides this until PR G, so `router.admin.test.tsx` mocks the gate to reach it. Hiding the item also stops `NavBadge`'s read of `/reconciliation/confirmed`, which would answer such a user 403.
  - `useNavItems` offers the admin's items only once `/api/me` says so, so a stranger never sees them flash by. The bottom bar holds five cells for the admin.
  - A real server answered the list with exactly the eight keys, on `strategy_manager_review`. The page was read in Edge in Spanish at desktop and 500 px wide, under the brake, with and without a key. 390 px was not seen: headless Edge does not go below 500 and an iframe did not draw the app. Open positions were 0 for everyone there, so a nonzero count is proven by the integration tests only.
  - Mutations: 25 of `mutate_f7a.ps1` on the backend and 48 of `mutate_f7b.ps1` on the panel, all killed and restored. Two panel survivors were real gaps, an entry that is not an object and `/users` outside its guard, and each got a test.
- [x] F.D Gate, independent verifier (a migration, and a read that crosses users on purpose), `rehearse_0036.sh` on a fresh backup, which also prints `visibility` by archived state, since `PUBLIC` in "Production now" is the owner's word, and its deploy script, every query exercised locally. Then push and PR on the owner's word, merge, deploy, the API's restart before pps.6 (a panel ahead of the API would offer a form whose route does not exist yet), the owner chooses their name, delivery log.
  - Gate after decisions 31 and 32, the last code of the PR: ruff 0, mypy 0, pytest exit 0 with no failing test; frontend lint 0, 117 files, 3,163 tests passed.
  - Verifier (Opus, at `65c44ac`): one blocker, B1. An invisible character passed `normalize_display_name`, because the check read only the `C*` categories while variation selectors are marks and the Hangul fillers are letters: `PUT /api/me/display-name` took `Ana Lopez` plus U+FE0F beside the real holder. Fixed in `6420df6`. The recheck found the same blocker on U+133FC, which draws no ink in Edge through the panel's fonts although Unicode gives it a glyph, so a second correction, `d427b8e`, refuses it and U+FFFC. That recheck's sweep over Unicode 15: of 267 Default_Ignorable code points outside the `C*` categories, none is accepted. `d427b8e` was proven by its own tests and mutations, with no third verifier run. Other browsers and fonts were not checked.
  - Closed from its advisories: `/api/admin` is `no-store` on every status and the flaky `37.5` test reads a share no clock's seconds can spell (`096925a`), a saved share refreshes the public capital (`674cb9b`), and `rehearse_0036.sh` prints the database locale and whether `lower()` folds an accented capital. Mutations: 19 of `mutate_fd.ps1`, all killed and restored. `rehearse_local_0036.py` answered `LOCAL RESULT: ok` after the locale lines were added.
  - Decision 32: a name cannot mix Latin, Cyrillic, Greek, Armenian or Cherokee letters, since Cyrillic `Аna Lopez` passed NFKC and the unique index beside `Ana Lopez` and read the same. A name wholly in one of them can still imitate another. Mutations: 8 of `mutate_fd3.ps1`.
  - Decision 31: a compounded return stops at -100%, in `compound`, so the public record, the pool and strategy curves, ranges and pairs all follow it. `monthly_grid` and `sliceAndRebase` would have divided by the zero the floor makes possible, so a month or a chart window that starts from zero reads 0%. Mutations: 8 of `mutate_fd2.ps1`.
  - Open, recorded under PR G: one strategy of crafted prices can answer 500 for the whole public list, a `PUBLIC` strategy of an unnamed author is reachable by id through preview and subscribe, a deleted key's seat still counts as live capital, `useVenueFollowUp` sends a non-admin to a page that says not found, and an author sees no capital sum on a private strategy. A 404 public page shows "loading" first, because the default `QueryClient` retries: a panel-wide pattern.

### PR F's delivery

PR #93 merged 2026-11-02 03:14 UTC as `60e5fb33a2d6`, with a merge commit. One migration, no dependency changed, 142 files, 74 of them in `frontend/`.

**PR F's deploy, 2026-11-02** (owner-run):
1. Pull as `strategy`, checkout `60e5fb33a2d6`.
2. `rehearse_0036.sh` on a fresh backup, `/root/sm_pre0036_20261102_0320.dump`: clean through upgrade, downgrade and upgrade again. Locale `en_US.UTF-8`, and `lower()` folds an accented capital. The real rows gave 3 strategies on the public list, each with 1 live subscriber and capital `328.12`, and 1 user on the admin's list.
3. `deploy_0036.sh`, 202 minutes into the 4h candle, 03:22 UTC (the script prints the VPS's clock, one hour ahead). Backup `/root/sm_pre0036_deploy_20261102_0322.dump`, alembic `0035` to `0036`, nobody named, the guard exits 0, both services active. The webhook and both new routes answer 401 unsigned. The only lines the WARNING/ERROR grep matched are the two `INFO` alert lines, known noise.
4. pps.6 after the API: `60e5fb33a2d6`, SHA-256 `a216e0246964ae007df99f2c41d39efaa682798c50062d3df3b202db0fb0eb1e`. `/root/panel-60e5fb33a2d6.tgz: OK`, `readable`, `bundle:   60e5fb33a2d6`, `checkout: 60e5fb33a2d6`.
5. The owner chose their name and read the capital on Explore, `328.12 USDT`, its first reading on a running server. They confirmed the delivery as correct.

**Not seen in production:** nobody but the owner can reach any of this until PR G, so a subscribe and a leave by another user, a name refused for real, and a public page read by a stranger stay proven by tests only.

**Asked by the owner on reading it, for the delivery they belong to:** see "Panel requests pending" below.

## Panel requests pending

Asked by the owner on 2026-11-02, after PR F's deploy, not built. None blocks PR G. Verbatim:

- "En strategies/explore agregaría a cada item age, closed trades, return... etc, un icono. La página se apoya demasiado en textos y debería empezar a aligerarse con más iconos que hablen por sí solos, y a lo sumo agregarles tooltips al pasar el mouse por encima para el que quiera corroborar de qué se trata. Todo lo que sea información sensible o que no se pueda malinterpretar que quede como textual, pero lo que no lo sea, puede pasar a este formato. No solo en strategies/explore sino en general, para que todo siga las mismas reglas."
- "Además, el botón de Leave en strategies my subscriptions, debería ser rojo, como el boton de delete key en settings. Sino tiene el mismo peso que el boton de change share."
- "La curva se empezó a dibujar directamente a partir de aproximadamente 3% de PnL y cayendo a 0% nuevamente. Idealmente, la curva debería empezar desde 0%, y subir al 3% en el primer tramo." Settled as decision 36: the 0 goes on the day the first trade opened, and needs one origin date in the curve's response.
- "Actualmente veo como pestañas Binance, Bybit y Pionex a pesar de solo tener la key configurada de Binance. Quisiera que solo se muestren las pestañas de exchanges configurados." Settled as decision 37: a tab shows with a key, an open position, or an active strategy or subscription on that exchange. The panel cannot tell that from what it reads today, so the server has to say it.

- Asked on 2026-11-06, to build together with decision 36 (the curve starts at 0): "En las curvas de overview y de las estrategias, cuando se elige la visibilidad All no aparece la fecha de comienzo ni la actual, ni fechas intermedias para tener de referencia. Es un detalle a agregar junto con los ajustes del gráfico partiendo de 0."
- Asked on 2026-11-06, after reviewing PR H's panel locally:
  - "Compactar el dialogo de strategy settings tanto en la vista de las estrategias como en la creación de nueva estrategia: input y botón de guardar en la misma fila. Resumir los botones Save, por ejemplo de 'Save share' a 'Save' (mantener el icono). Resumir 'Ask for about x USDT...' e indicar cuánto margen pide, y si hay apalancamiento, el nocional. Al mover el botón junto al input, puede ocupar el ancho disponible."
  - "En la descripción de estrategias dar formato a los links para que sean cliqueables. Por ejemplo mi estrategia se explica en detalle en un artefacto de Claude, por lo que adjunto ese link ahí." Constraint carried from H.8: the description stays plain text, never HTML or Markdown. Only `http`/`https` URLs become links, opened with `rel="noopener noreferrer"`.
  - "En /strategies cambiar el botón Authored por My strategies y agregarle iconos a cada botón de ese nav."

## Possible improvements

Noted on the owner's word, not built, not scheduled.

- **Same-day returns are summed, which is exact only for trades that overlap** (raised by the owner 2026-11-06). Decision 17 sums `r_i = pnl_i / pool_total_at_open_i` within a UTC day and compounds across days (`performance/domain/curve.py`).
  - The owner's case: "Es común que dos pares operen el mismo día, y ambas suelen abrir con el mismo monto, pero a veces una deja una ganancia y la otra abre con un monto mayor. O si la primera pierde, la siguiente abre con monto menor."
  - Two trades that overlap in time are sized against the same capital, so their sum is exact. When the second opens after the first closed, its denominator already holds the first's result. For those trades compounding is exact, and the sum misses `r1 * r2`. Two sequential +3 % trades show +6.00 % where the pool grew +6.09 %. Two -3 % trades show -6.00 % against a real -5.91 %. +3 % then -3 % shows 0.00 % against a real -0.09 %.
  - The error accumulates. The curve's ratio to the truth is about `exp(-sum of r1*r2)` over the sequential pairs. When same-day results share a sign the error always leans conservative (gains under-reported, losses over-reported), and it grows linearly with the number of such days. Mixed days cancel part of it. It scales with the square of the per-trade return: 100 same-sign days at 1 % per trade cost about 1 % of the index, and at 3 % about 9 %.
  - The exact rule compounds trades in close order when one opened after the other closed, and sums only trades that overlap. Cost: a more involved rule, and the whole published history is recomputed.
  - Before deciding, measure it on real fills: compute both curves over production's ledger, per pool and per strategy, and compare their end indices.
  - Measured on production 2026-11-06 (owner's run of `scripts/compare_same_day_returns.py`). The owner's binance/usdt-m/USDT pool: 15 trades over 12 days, one day with trades that followed each other. Summed +15.03%, exact +15.05%: the panel shows 0.026 points less (0.022% relative), the largest day gap 0.023 points. Every strategy alone: 0 days with sequential trades, so the two curves are identical. The error is conservative and too small to act on now; rerun the script when the record is longer or more pairs trade on one day.
  - **Done, decision 40 (2026-11-06).** The owner chose to make the exact rule the only one now, while it moves the history by 0.026 points, rather than later, when it would move published numbers visibly. `combine_by_day` in `curve.py` replaces `sum_by_day` for the panel's curve, months, ranges, per-pair figures and the public record (`RecordTrade` gains `opened_at`). The measuring script is removed with it, since both of its curves are now the same; it stays in commit 2aa8530. The fixtures of two read tests built trades that opened and closed in the same instant, which no real trade does; they now open an hour before they close.
  - *Script written 2026-11-06* on the owner's "Lo que recomiendes primero": `backend/scripts/compare_same_day_returns.py`, read-only (one `READ ONLY` transaction, no exchange call). It reads the same trades the panel reads (`pool_fills` -> `derive_trades`). For every pool and every strategy in it, it prints: trades, days, days with more than one group, both total returns, the gap of the end index, and the largest gap of one day. The pure part is tested in `tests/scripts/test_compare_same_day_returns.py`: overlap is summed, a trade opened at or after a close is compounded, and a group lasts until its last member closes. 8 of 8 mutations killed (`mutate_sameday.ps1`). Its queries ran against the local review database (6 pools, no fills). Still owed: the owner's run on production and its numbers.

## PR G

Planned in `design.md`, "Delivery": readiness D.1 to D.5, `SignInGate` opens, the Access policy opens, seat expiration turns on. Its tasks are written when PR F is merged. D.5 is the price check of decision 29. Advisory A3 of PR E2 is still open and needs its design before sign-up opens: it reaches any subscriber. Found in F.6, to close before sign-up opens: `PositionsTable` and `StrategyLink` link every strategy to `/strategies/:strategyId`, which is author-only, so a subscriber's own position links to a page that answers not found. Found by PR F's verifier, to close before sign-up opens: the public list must survive one strategy of crafted prices (`wire.py:48` raises `InvalidOperation` above 80 digits, and decision 29 says an author can post them), and preview and subscribe must follow the page for a strategy that is off the list.

### PR G's plan (2026-11-02)

The panel opens to every signed-in user, and Access opens last. Until G.D's last step production stays what it is: Access admits the owner, plus one test address for D.2. One PR, no migration since decision 34 replaced the price check. Owner's word per unit.

**The map, read at `c8bf0d2`:**
- **a.** `SignInGate.tsx:30` is the one line that stops a non-admin. Behind it, `/discrepancies` and `/users` are already under `AdminRoute`. Three things still assume the admin: `ExchangeTabs.tsx:40` draws no tabs for anyone else, so a user keyed on two exchanges could not switch between them; `/api/webhook-origin` answers a non-admin 403 (`webhook_origin_router.py:36`), so their issued URL carries only the path; and `useVenueFollowUp` asks `/api/reconciliation/confirmed`, which answers them 403.
- **b.** Correction to what F.D recorded: `useVenueFollowUp` does not send a non-admin anywhere. On the 403 `data` stays undefined and it returns null (`useVenueFollowUp.ts:41`). What remains is a refused read on every marked line.
- **c.** 34 `/api` routes. `test_every_api_route_is_guarded.py` lists them from the app but checks the guard, not cross-user data. The cross-user tests live per router, and nothing demands one per route.
- **d.** The worker runs one job at a time (`job_queue.py:110-122` `.limit(1)`, `worker.py:260`). So a fan-out's deliveries run one after another, and nothing measures how long that takes.
- **e.** `/fapi/v3/account` weighs 5 of Binance's 2400 per minute, per IP (`config.py:290-296`). A balance sync makes one such call per (user, exchange) every 60 s, so 50 users add 250. The reconciliation's weight still has to be added to that.
- **f.** No adapter reads a venue's price without a key, and `signals` has nowhere to put one.
- **g.** `wire.py:48`: `read_all` builds every strategy in one pass, with no per-row guard, so one ratio over 80 digits fails the whole list. Read from the code, not run yet.
- **h.** The page's `_LISTED` requires the author's name; preview (`strategies/infrastructure/router.py:712-720`) and subscribe (`subscribe.py:45-52`) do not.
- **i.** `PositionsTable.tsx:129` links every row to the author-only `/strategies/:id`. `StrategyLink` is only on admin pages, so it needs no change.
- **j.** `live_seats` (`public_strategies_source.py:121-141`) reads no credential, so a deleted key's seat stays in the capital and in the live count.
- **k.** Decision 10 gives an author the capital their subscribers assign. `StrategyView` carries only counts, and the capital sits on the public body, so the author of a private strategy sees none.

**Decisions stated, not asked:**
- **Preview and subscribe answer as the page does** when the author has no name. An archived strategy keeps subscribe's 409.
- **D.2 runs before Access opens**, by adding one test address to the policy, on the deployed code with the gate already open. If it fails, nobody else got in.
- **Left out on purpose:** the 404 page that shows "loading" first (a panel-wide retry pattern that shows no wrong data), and the two panel requests of the section above.

**Found on 2026-11-02, to close before sign-up opens:** a live opening is sized from the alert's price. `process_signal.py:781` passes `context.price`, which is `signals.price`, and `binance_futures_exchange.py:115` and its Bybit twin compute `granted * leverage / price` from it. An author who posts a tenth of the market price opens every live subscriber at ten times their granted margin, limited only by what the venue's margin allows. Decision 29's check would not stop it, since it only touches the public record. Harmless while the owner is the only sender.

**Tasks.** Each is a work-unit commit, strict TDD.

- [x] G.1 The public list survives a strategy it cannot serialise (map g). One such strategy is left out and logged, and the list answers. Its page behaves the same as any off-list strategy. RED on a crafted record through the router: two days of the widest prices a signal can hold answered 500 for the list and for the page. The guard sits in the router, because the 80-digit limit is the wire's.
- [x] G.2 Preview and subscribe follow the page (map h): one shared rule, not a third copy of `_LISTED`. The author and a holder keep their reach. `offered_to_others` in the strategies domain, read through the existing `has_display_name`; subscribing answered 201 and the preview 200 before it. Mutations: 7 of `mutate_g2.ps1`, all killed.
- [x] G.3 Capital counts a seat only if its user has a trade-capable key on that exchange (map j), reusing the capability the opening's key check reads. The author's view carries the capital of their strategy, private ones too, simulated subscribers left out of the sum as in decision 30 (map k). `has_trade_capable_key` is one clause shared by the public seats and the author's `live_subscribers`, so the two counts cannot disagree; a seat in `LIVE` with no key, a read-only key, an inactive key or a key on another exchange counted before it. `StrategyView.capital` is the same `public_capital` the public list adds up, null under the `DRY_RUN` brake; `AuthorCapital` draws it on the row and the header and draws nothing when it is null. Mutations: 15 of `mutate_g3.ps1`, backend and panel, all killed.
- [x] G.4 The panel for a non-admin (map a, b, i): `ExchangeTabs` opens; `/api/webhook-origin` opens to any signed-in user and moves to the scoped list of `test_every_api_route_is_guarded.py`; `useConfirmedDiscrepancies` does not run for a non-admin; a position's link goes to the detail page for its author, to the public page for a listed strategy, and is plain text otherwise. Read in Edge as a non-admin, at desktop and narrow width. The server says which page a position reaches (`strategy_page`: `AUTHORED`, `LISTED` or null), read in the facts' own statement through `LISTED`, now shared with the public list, so a link cannot lead to a page that answers 404. `useVenueFollowUp` sends no request for anyone but the admin; `useConfirmedDiscrepancies` takes `enabled`, because `me.ts` already imports its key and the hook reading `useMe` would close an import cycle. Read on `strategy_manager_review` with the review's owner as a non-admin and the gate passed through (it opens in G.10): five pages at both widths, 8 routes read, no refused read, no Discrepancies or Users in the navigation. Headless Edge cannot press a tab, so the three kinds of link are pinned by tests, not seen. Mutations: 19 of `mutate_g4.ps1`, backend and panel, all killed; the 9 of the backend were run twice, because the first run had a test already failing under `-x` and proved nothing, so the script now refuses a baseline that is not green. `/api/webhook-origin` now reads `users` through `current_user`, so the tests that served it with no database answer it through `without_a_database`. Left for G.D: My subscriptions links a subscriber to the public page even off the list (`MySubscriptionsPage.tsx:37`), where it says not found; it shows nothing wrong, and it is not this task's link. In G.D.3 the API restarts before the panel moves: the new panel refuses a positions answer with no `strategy_page`, and the old panel ignores the extra field.
- [x] G.5 D.1, the cross-user sweep (map c): one test takes the route list from the app and fails on any `/api` route with no cross-user probe, and each route has one. A route that turns out to leak is fixed in its own commit. `test_cross_user_sweep.py`: 34 probes over the 31 routes that do not require the admin, in one world where B stands as close to A as a user can: a pool on A's market and a seat on A's public strategy. A probe naming a thing of A's answers 404, moves no row, reads the same as an id nobody holds, and A asking the same is not a 404, so the 404 is not a typo. A probe of B's own answers its status, with nothing of A's in the body and no row of A's moved. The three admin routes stay proven by their 403 in `test_every_api_route_is_guarded.py`, and `is_admin` decides nothing in any scoped route. **One leak, fixed in 0095e03:** `GET /api/performance/strategies/{id}` and `/trades` loaded the strategy with no scope, so any signed-in user holding a private strategy's id got a 200 naming its exchange, venue and currency, with empty figures. Those figures were always the asker's own, and a test from PR B pinned that 200. They now answer 404 unless the user wrote the strategy or holds or held a seat on it, an ended seat included. Mutations: 26 of `mutate_g5.ps1` and `mutate_g5b.ps1`, each a user filter removed and only the sweep run, 24 killed. The two survivors are redundant filters, not gaps: the ledger's `user_id` in `allocation_fills_source.py` stands behind the reservation's on the same join (both removed is killed), and the unlocked `get` in `leave.py` stands before the `get_for_update` that decides. The first run also caught the sweep short: an order in flight carried no trace and no order id, so its filter could go unseen. The public list shows a strategy's capital to everyone on purpose (decision 30), so that one trace is exempt on that one route.
- [x] G.6 A3: a close waits for an opening in flight. Needs its design first: `_holds` reads no attempt, there is no fill yet to act on, and the shape to mirror is `OpenAfterClose`. Written into this section before any code (below, "G.6's design"). Risk item 4. Built as designed, departures under "What building it changed". `_holds` reads reservation, then attempt still `SUBMITTED`, then ledger, so a holder whose reservation the sweeper expired while the order was in flight still receives the close. The close then asks `next_close_step`: proceed on a booked row or a `FILLED` attempt, wait on a `SUBMITTED` one (a `delivery.process` job one poll interval on, `delivery:{id}:after-opening:{poll}`), end `REJECTED` `NO_POSITION_TO_CLOSE` with a WARNING when the opening was never placed, and `REJECTED` `CONTINUATION_TIMED_OUT` with an ERROR past `close_after_open_timeout_seconds` (600 s, longer than the settle job's 452 s, pinned by a test). The premise was confirmed before the code: with the opening's job marked done, as the worker's ack does, the close of window 2 reached nobody (`assert set() == {author, other}`). Mutations: 31 of `mutate_g6.ps1`, all killed, on a green baseline. Not tested: the order of the three reads in `_holds`, which only matters in a race the serial worker cannot produce; G.7 owes that proof or G.D.1's verifier reads it by name. A reverse that waits long enough can close and then have its open abandoned at the 600 s signal age, which is the existing, safe behaviour.
- [x] G.7 D.3, fan-out latency (map d, e): measure one signal to 20 simulated subscribers on real PostgreSQL, and write down the Binance weight for 50 users, reconciliation included. Design says a serial worker gets its concurrency raised, so this unit carries that change, deliveries only: two signals of one strategy must stay in order. Lock-hold harness. Risk item 4. Built as "G.7's design" below says, with settles in the lanes too, so a settle never runs beside its user's next delivery. Measured: the twentieth of 20 subscribers opens at 4.83 s with four lanes, 21.00 s serial. `test_user_job_lanes_integration.py` proves the per-user order on the real claim, the lock-hold harness through `WorkerRunner` (A's delivery paused, B's open and close run to the end, A's close not started until A's open ends), the unreadable-user barrier both ways, the wiring, and G.6's read order across a settle committed between `_holds`' reads. Mutations: 24 of `mutate_g7.ps1`, 23 killed on a green baseline. The survivor is redundant, not a gap: a lane's `kind IN` filter stands behind `user IS NOT NULL`, since no first-loop kind names a delivery or an attempt. Binance weight written down below: over the ceiling at 50 users on one signal, not changed here, recorded for the owner's word.
- [x] G.8 D.5, replaced by decision 34: the public record reads the author's real trades, from the ledger. Their fills per allocation, through `derive_trade`'s existing fold and never the rehearsal ones, give each trade's return, unleveraged and before fees; decisions 28 and 31 still add them up. `closed_trade_count` follows. A strategy with no real closed trade is listed with no return and says so, EN and ES. `test_the_read_runs_in_one_read_only_snapshot_and_touches_no_ledger_or_payload` and the record's module note change with it: the body still carries no amount. Risk item 3. Built 2026-11-03: `PublicStrategiesSourcePort.signals` became `author_fills`, one statement over `ledger_entries` joined to `strategies` on `user_id = author_id`, the rehearsal prefix left out as `SqlAlchemyAllocationFillsSource` leaves it, grouped as that source groups. `public_record.py` folds them through `derive_trades` and takes each closed trade's return from the notionals (long `sold / bought - 1`, short `1 - bought / sold`), so leverage and fees never enter; it refuses rehearsal groups again in case a source lets one through. `ledger_entries.notional > 0` by CHECK (0005), so nothing divides by zero. An allocation whose symbol cannot be split is named in a WARNING by `ReadPublicStrategies`, never dropped silently. The wire is unchanged: `unleveraged_return_before_fees` stays `"0"` with `closed_trade_count` 0, so the deployed panel reads the new API as it read the old one. The panel writes "no real trade yet" / "todavía sin operaciones reales" there, and `returnHint` says where the figure comes from, EN and ES. The snapshot test became `..._touches_no_signal_or_payload` (four statements, none on `signals`), and the import test now pins that the record, port, use case and source import no `signals` module, so an alert's price cannot reach a record. Mutations: 13 of `mutate_g8.ps1`, all killed on a green baseline (author filter, rehearsal in the source and in the record, long and short formulas, direction, order, open trades, zero, compounding, unresolved ids, the warning, fees).
- [x] G.9 A live opening is sized from the venue's price (decision 35). Binance and Bybit read it at order-build time, as they read the leverage, and an unread price refuses that opening. A close is untouched. To settle in this unit: a simulated fill prints at the alert's price (`fake_exchange.py:214`, `:336`), so a crafted alert still reaches a simulated subscriber's own ledger and pages, and a simulated user may have no key to read a price with. The sizing path moves real money, so G.D.1's verifier reads it by name.
  - *The live part, built 2026-11-03.* Both adapters read the venue's MARK price beside the leverage and size `granted * leverage / mark` from it. The minimum-notional check reads the same price, and `spec.price` sizes no real order. The mark is used rather than the last trade because margin and liquidation are computed from it, and one print on a thin book cannot move it. Binance reads `GET /fapi/v1/premiumIndex?symbol=`, which is public and costs IP weight 1 (docs checked 2026-11-03), so an opening now costs about 22 instead of 21. Bybit reads `markPrice` off `/v5/market/tickers`, matched by symbol. Either read refuses anything but one positive, finite price of the asked symbol, sent as a string. The raw venue error propagates, so `PlaceOrder` retries and the reservation's expiry ends it, exactly as for an unread leverage. A close reads no price. `check_binance_read.py` probes `premiumIndex` per symbol, because the live field match is unverified, and `check_bybit_sizing.py` renders at the mark. RED on assertions: the wire test sent 1295.0 instead of 129.5, the adapters sized 16.1 instead of 1.6 and 0.128 instead of 0.012, the unread price did not raise, and the clients returned the skeleton's 1. Binance's floor-at-the-venue's-price test passed at once and is proven by mutation. Mutations: 15 of `mutate_g9.ps1`, all killed.
  - *The simulated part, settled and built 2026-11-04 (owner: "Dale, si", decision 35's second paragraph).* A simulated fill prints at the venue's mark price, not the alert's. `venue_mark_prices.py` reads it from each venue's PUBLIC endpoint, so no key is needed: `premiumIndex` on Binance and the linear ticker on Bybit, with the bare symbol, one short-lived HTTP client per read. The answer goes through the same `parse_mark_price` the signed read clients now share, so a simulated opening refuses exactly what a live one refuses. `FakeExchangeAdapter` takes `mark_prices`. With it, the mark sizes the opening and prices both fills, and the alert's price is never read. An unreadable mark raises the venue's own error from the build, so the job retries, as a live opening does. Without it (tests that pin the arithmetic) the alert-priced mode is unchanged. `main.build_worker_runner` wires a source to every simulated exchange by key. The startup INFO now says "the venue's mark price", and a fake built without a source is a WARNING naming it. No test reaches a venue: an autouse fixture refuses every read (`tests/venue_marks.py`), and the tests that fill through the real wiring install a price. The end-to-end file now sends every alert at a tenth of the market and still asserts 1250 STX at 0.4512. A stored-NaN close no longer stops a simulated close: it fills at the mark. The panel needed no change: a new simulated operation is neither at its alert's price nor at 1, so it reads `UNDETERMINED` and shows the plain "Dry run" label, which makes no claim about its price, while old rows keep theirs. RED on assertions: the readers returned the skeleton's 1, the fake asked no price, and the venue error did not raise. Mutations: 11 of `mutate_g9b.ps1`, all killed.
- [x] G.10 D.4 and the gate, last: `CLAUDE.md` rewritten for one key per exchange per user (lines 192-206 and 380-381; rule 4 is already per user), and `SignInGate` lets every signed-in user through, with its docstring.
  - *Built 2026-11-04.* `CLAUDE.md`'s credentials section now reads one key per user and exchange: the active-key index is on `(user_id, exchange)` since 0030 (verified in `models.py`), saving supersedes only that user's key, a user with no key is DEGRADED alone (decision 20), the user saving a Binance key confirms it, the worker refuses to start on any user's key that does not open, and a probe signs for its `--user-email`. The Safety line says the same. `SignInGate` lets through any user `/api/me` confirms; the admin's pages stay behind `AdminRoute`, and who may sign in at all is Access's policy (G.D.5). The unused `auth.gate.notOpen` copy is gone from EN and ES, and `router.admin.test.tsx` no longer mocks the gate, so its "not found for anyone else" cases now run past the real one. RED on an assertion: a non-admin did not see the protected content.

#### G.6's design (2026-11-02)

**What fails today.** `SettleExecution` books an opening's fills, its attempt's `FILLED` and its reservation's `FILLED` in one transaction, and an order the venue knows with no fills published yet retries on the job backoff: 2 s, then 30, 60, 120, 240. So an opening can stay `SUBMITTED` for up to about 452 s. The reservation expires at its 30 s TTL meanwhile. There are two windows, and a close lands in one of them:

1. *Reservation still live.* `_holds` is true, the close is delivered, `ClosePosition` finds an empty ledger and raises `NothingRecordedYet`, and the delivery job retries on the same backoff. The position closes, but up to 240 s after the fill, on a position the strategy already left. If the opening was never placed, the job spends all five attempts on it and ends `JOB_FAILED`, on a subscriber who holds nothing.
2. *Reservation expired.* `_holds` is false, so the close reaches nobody and the signal ends `NO_POSITION_TO_CLOSE`. The fill lands later and nothing ever closes it. This is the hole A3 names.

`_holds`' docstring says delivering would not help because there is no fill yet. That is wrong: window 1 already proves a delivered close can wait. What it lacks is a wait that is prompt and that ends.

**The design.** One rule, for both windows: *a close whose opening is still in flight waits for it, polling the database, and then runs.*

- **Fan-out reaches the holder.** `_holds` reads an opening attempt in flight the way `OpenAllocationAdapter` does, by its attempt and not its reservation, on this strategy, market and symbol under every spelling. The reads change order to reservation, attempt, ledger, the order exposure moves in, so a settle committing between two reads cannot hide a holder. It cannot happen on today's serial worker; G.7 makes it possible.
- **The delivery decides.** `_handle_releases` asks `CloseAfterOpen.step(user, allocation)` first, before anything else about the close. `next_close_step`, a pure function, reads the opening's attempt status, its age and whether the ledger holds a row of the allocation:
  - no attempt, or a row already booked, or an attempt `FILLED`: `PROCEED`, today's path, `NothingRecordedYet` included, as the backstop;
  - `SUBMITTED` younger than the bound: `WAIT`;
  - `SUBMITTED` past the bound: `TIMED_OUT`;
  - `FAILED` with nothing booked: `NOTHING_OPENED`.
- **`WAIT` re-enqueues the delivery.** A `delivery.process` job with the same `delivery_id` and `halves`, `poll + 1`, `run_after` now plus `open_after_close_poll_interval_seconds` (5 s), under the dedupe key `delivery:{id}:after-opening:{poll}`. So a redelivered job is the same step, and each poll a new one. The same kind and the same handler carry the subscriber's own key; there is no new kind, so no migration. A wait is not a failure: no attempt is spent, and the result says `waiting`, so a reverse on a pool that cannot hold the new side does not report its tail before its close has run.
- **`TIMED_OUT` ends the delivery `REJECTED` `CONTINUATION_TIMED_OUT`, at ERROR, which reaches Telegram.** It says a human must act, because a fill can still land. `close_after_open_timeout_seconds` is 600, from the attempt's `created_at`. The bound has to outlast the settle job, or a close gives up on an opening that is still going to fill; a test pins it above 452 s from the settings it derives from.
- **`NOTHING_OPENED` ends it `REJECTED` `NO_POSITION_TO_CLOSE`, at WARNING.** Nothing was opened, so nothing was left open. For a reverse it says the new side was not opened, as both sibling refusals do.

**Why these and not the mirror image.** `OpenAfterClose` gives up on a newer signal, because an opening is an intention TradingView has replaced. A close is not superseded: the position it would close is real whatever came next, so nothing here reads `has_newer`. Nor does the signal's age end it: a late close still closes. Only the opening's own bound ends the wait. It needs no job kind of its own because all it does next is run the delivery again, and `handle` already does everything a close needs, the idempotent release half and a reverse's seed included.

**Left as it is.** An opening signal arriving while a close waits still goes through the guard's in-flight branch; if the fill lands first, that opening can be refused as already holding, moments before the close runs. It takes three signals inside a market order's settling time and it is what happens today. A reservation with no attempt yet cannot be met on the serial worker and stays on the `NothingRecordedYet` backstop.

**Checks.** Real PostgreSQL through the delivery flow's world: both windows, the same close run twice, an opening never placed, the bound, a reverse waiting and then closing and opening, and the chain going past its second poll through the worker's own handler, since a poll not threaded would collide on its dedupe key and die with no log line. Unit: `next_close_step`, including the edge of the bound. Fan-out: in flight on this symbol, on another, of another user, and `FAILED`. Mutations over all of it.

**What building it changed.** Three small departures from the text above. `NOTHING_OPENED` covers every final status with nothing booked, not only `FAILED`: `ABORTED_EXPIRED` is as final, and leaving it out would wait on it for the full bound. The poll chain is proven in two halves, not one: `ProcessDelivery` seeding each step after its own, through the delivery world, and the worker's handler handing the job's poll to `handle`, through `runner._handlers`. And a never-placed reverse is pinned by its detail, as is a plain close's lack of it. The seed is not committed in the use case: the job handler's commit makes it durable, as it does for the guard's seed. The order of the three reads in `_holds` has no test: it matters only under a race the serial worker cannot produce, so G.7 owes that proof or G.D.1's verifier reads it by name.

#### G.7's design (2026-11-03)

**What is slow today.** `WorkerRunner.run_once` claims one job and awaits it before the next (`worker_runner.py:44`), so one signal's deliveries run one after another. In simulation that costs only database time. Live, every opening makes four or five venue round trips (the pre-allocation balance read, the leverage, the position mode, the order) and the last subscriber of twenty opens about twenty such sequences after the first.

**The design.** Deliveries run in parallel across users, and never two of one user at once.

- **Lanes.** `run_forever` runs the loop it runs today, which claims every kind, plus `worker_delivery_lanes` more loops (default 4) that claim only a user's trading jobs: `delivery.process`, `signal.open_after_close` and `execution.settle`. They run in one `asyncio.TaskGroup`, so an error out of any loop ends them all and the process, as it does today. The tick hook stays on the first loop. Every other kind (fan-out, sweep, sync, scan, booking, purge, watchdog) runs only on that loop, so those stay serial among themselves.
- **One user, one at a time, in order.** The claim reads each such job's user from what its payload names: the delivery's (`delivery_id`) or the attempt's (`execution_attempt_id`). No payload changes, so the jobs already queued at deploy are covered. A job of those kinds is claimable only when no other PENDING job of those kinds for the same user comes before it, by `(run_after, id)`. `claim` never commits until its job ends, so another claimer still reads a job being worked as PENDING, and that keeps every later job of that user waiting until it is acknowledged. A job that fails goes back with a later `run_after` and stops blocking, which is what the serial worker does today. So two signals of one strategy reach one subscriber in order, a settle never runs beside its user's next delivery, and the opening-then-close order `_awaits_opening` relies on still holds per user.
- **A job whose user cannot be read** (a legacy `signal.open_after_close` that carries only `signal_id`) is claimed only by the first loop, and only once every such job before it has ended; every later one waits for it. It is a barrier, not a guess.
- **Connections.** A job holds about two (the claim session and the handler's). Five loops hold ten, under the engine's default fifteen, so no pool setting changes.

**What overlaps now, and why it is safe.** Only jobs of different users, and first-loop jobs beside a user's jobs. Users share no pool and no lock. Of the first-loop kinds, fan-out reads what a settle writes, and that is the race the order of `_holds`' reads was written for in G.6: a settle can now commit between two of them. So G.7 proves it: a settle committed right after the reservation read, on a holder whose reservation expired, still finds the holder. The sweeper could already expire a reservation under an order in flight (`PlaceOrder` answers `ABORTED_EXPIRED`), and the sync and the scan only read the venue and write their own rows.

**Checks.** Real PostgreSQL. With the lock-hold harness: a delivery of user A paused holding its claim, user B's delivery runs to the end meanwhile, and A's next delivery does not start (`not task.done()`) until A's first is acknowledged. Two signals of one strategy to one user, the second never claimed first. A settle blocks its user's later delivery. A job whose user cannot be read is never claimed by a lane and holds back the jobs after it. A failed job stops blocking. A lane never claims a first-loop kind. `_holds` across a settle committed between its reads. The wiring: the worker's runner has the lanes the settings give and its queue applies the rule. Then mutations.

**Measured (2026-11-03, local PostgreSQL, scratch test not committed).** One opening fanned out to 20 simulated subscribers on one strategy, each worked by the real `ProcessDelivery` with its own pool and venue, the venue holding every order 1 s as a live round trip would. Serial (`lanes=0`): the first opened at 1.17 s, the last at **21.00 s**, about 50 ms of database work per delivery besides the venue's second. With the default four lanes: first at 1.49 s, last at **4.83 s**. 20 orders placed in both. Five loops take about a fifth of the time, as they should; the database is not what binds.

**Binance weight for 50 users** (per IP, ceiling 2400 a minute; [Account Trade List](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Account-Trade-List) 5, [New Order](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order) 0, [Query Order](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Query-Order) 1, [Get Current Position Mode](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Get-Current-Position-Mode) 30; `/fapi/v3/account` and `/fapi/v3/positionRisk` 5, measured in Phase 0, `config.py:297-301`; `/fapi/v1/symbolConfig` not confirmed, counted as 5):
- *Steady:* `balance.sync` reads `/fapi/v3/account` per user every 60 s, 5 a minute, and `reconciliation.scan` reads `positionRisk` per user every 30 s, 10 a minute (`main.py:1970`, one scan per user). That is 15 a minute per user, **750 for 50**, about 31%, already over the 20% polling allowance `config.py:302` budgets, which assumed one reader.
- *Per live opening:* balance 5, leverage 5, position mode 30 (read on every job, since the client is built per job, `trade_client.py:198-204`), order 0, settle 1 + 5: **about 46**. A close is about 41. So one signal to 50 Binance subscribers spends about **2,300**, and with the steady 750 it passes the ceiling inside that minute. Lanes do not change the sum. Binance answers 429 past the ceiling and bans the IP when that is ignored.
- *Not changed by G.7.* The cheapest lever is the position-mode read (30 of the 46): read once per user rather than once per job. Recorded for the owner's word as a unit of its own. It needs one fact first: whether the venue itself refuses a one-way order on an account switched to hedge mode since the read, which nothing here has verified.

- [x] **G.7b (2026-11-03, owner: "Lo que convenga").** The mode is now read from [`/fapi/v1/accountConfig`](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Account-Config), weight 5, which carries the same `dualSidePosition` as `/fapi/v1/positionSide/dual` at 30. Still read on every job, so no cached mode can go stale and the hedge-mode fact above is no longer needed. An opening drops to about **21**, a close to about **16**; one signal to 50 Binance subscribers spends about 1,050, and with the steady 750 that is about 1,800 of 2,400 (75%). If the venue's payload ever lacks the field, the existing guard refuses the order loudly (`an unreadable position mode stops the order`), never silently. `scripts/check_binance_read.py` now probes both endpoints, so their `dualSidePosition` can be compared on the live account. RED: `test_the_position_mode_is_read_from_the_account_configuration` failed with DID NOT RAISE against the old path. Still open: the steady 750 is above Binance's 20% polling allowance, and a burst of signals in one minute can still pass the ceiling.

**Delivery.**
- [x] G.D.1 Gate (backend and frontend), and an independent verifier over the whole PR: it names items 2, 3 and 4, and the sizing of a live order.
  - *Done 2026-11-05.* Gates green on these trees: backend at `aaf7170` (no backend change since), frontend at `1f5f868` (3181 tests). The Opus verifier, read-only, found **no blockers**: security, contracts, concurrency, live sizing, simulated prices and the hedge-mode refusal all PASS, and G.1-G.10 are covered. Advisories:
    - **A1.** `live_holders` evaluates `_awaits_opening` after `_holds` (`fan_out_adapters.py:82-85`), although a pending delivery is the first state in the chain (delivery, reservation, attempt, ledger). A delivery that reserves after the reservation read and is acknowledged before the `_awaits_opening` read would leave a close reaching nobody. Its whole run, venue calls included, would have to fit inside fan-out's reads, so it is not realistic. Fix: read `_awaits_opening` first.
    - **A2.** The Pionex adapters still size from `spec.price` (`pionex_futures_exchange.py:99`, `:108`, the spot SELL in `pionex_exchange.py:104`). They are dormant, because they are not registered. The `OpenOrderSpec` docstring (`execution/application/ports.py:110-119`) still names `price` as the futures sizing input.
    - **A3.** Deploy order: the API restarts before the panel link moves (already noted under G.4).
    - **A4.** `openspec/changes/operator-panel/specs/trade-execution/spec.md:398-403` still requires the INFO line "prices each fill at its alert's price". Decision 35 superseded it.
    - **A5.** A simulated spot pool on Bybit or Binance would price at the linear perpetual's mark price. When the symbol has no linear contract, the job retries until it fails. This only matters if such a pool exists.
    - **A6.** A failed mark-price read keeps a reservation with no attempt alive. A close delivered meanwhile backs off for about 452 s and then ends loudly. The outcome is correct but noisy. A failed leverage read already behaved the same way.
  - *A1, A2 and A4 fixed 2026-11-05 (owner: "Dale, arreglalo").*
    - **A1.** `live_holders` now reads the pending delivery before `_holds`. RED: `test_an_opening_run_to_its_end_during_the_holders_reads_still_finds_the_holder` runs every opening to its end just before the delivery read, and with the old order it lost the author. That test is the mutation that proves the fix.
    - **A2.** The `OpenOrderSpec` docstring now says `price` sizes no real order and prices no fill. It names the dormant Pionex adapters as the one remaining reader of `price`.
    - **A4.** The trade-execution spec's startup line now says "venue's mark price". It also adds the alert-priced WARNING.
    - A3, A5 and A6 are left as recorded.
- [x] G.D.2 Push and PR (owner's word), merge (owner), with a merge commit.
  - Pushed and opened as #94 on the owner's "Si, por favor", 21 commits over `60e5fb3`. Merged by the owner on 2026-11-05 as `b5129b0`.
- [x] G.D.3 Deploy, then pps.6. No migration to rehearse. Access unchanged.
  - Deployed by the owner on 2026-11-05.
  - Backend: pulled as `strategy` to `b5129b0fc6fb`, and restarted both services, both `active`.
  - The worker's start line reads "the simulated exchange prices each fill at the venue's mark price and charges the venue's taker fee in USDT (binance=0.0005, bybit=0.00055)". No ERROR or Traceback line followed the restart.
  - Then pps.6: the assistant built the bundle from a detached worktree of `origin/main` at `b5129b0fc6fb`, 22 entries, SHA-256 `75bcdbef54d3b7842053b0501ece991437c716ece9f0eb874e8c2a9bb034fb39`. The owner's block printed `OK`, `readable`, and `bundle` and `checkout` both at `b5129b0fc6fb`.
- [ ] G.D.4 D.2, owner-run: add one test address to the Access policy and sign in with it, by one-time PIN and by Google. Check the `email` claim on a real token, that the user is created, and that they see nothing of the owner's. Google has to be enabled as an identity provider first.
- [ ] G.D.5 Owner-run: the Access policy admits every authenticated identity (decision 2), and seat expiration turns on (Zero Trust > Settings > Admin controls). Delivery log and "Production now".

**Incident, 2026-11-05: a live PNUT opening at Binance's 20x default.**
- **What happened.** A new strategy's first PNUTUSDT.P signal opened live at 01:00 at **20x**.
  - The owner's default of 2x isolated had never reached that pair. Binance applies a user's default leverage and margin mode to a symbol only after its trading page is visited, and API orders do not reflect the default until then ([FAQ 360034946672](https://www.binance.com/en/support/faq/360034946672)). The system default for an "Advanced" account is 20x.
  - The worker read `leverage = 20` from `/fapi/v1/symbolConfig` and sized at it. Margin 328.55 USDT, 174,575 PNUT, notional 6,579.37, roughly ten times what 2x would have opened.
  - The close came by signal at 15:56. Result: −326.55 from the move and −6.42 in fees, −332.97 USDT, which is more than the margin. That points to cross margin, an inference.
  - Nothing logged a warning. The system only reads leverage, and does not check `marginType` even though `_parse_symbol_config` parses it.
- **The owner topped the account back up** to its previous balance of 1095.17 USDT.
- **The round trip was deleted from the ledger at the owner's request**, so that it leaves their curve. It was rehearsed first on a copy restored from a backup.
  - Deleted: reservation `de7bcb64-3359-44ae-9dbb-8f177860a54c`, its 2 attempts and 75 fills, inside one transaction with the append-only triggers disabled and re-enabled (precedent: 0019).
  - Kept: both signals (their idempotency keys stop a replay), both deliveries, and the jobs.
  - Backup taken before the delete: `/var/backups/strategy-manager/pre-pnut-delete-20261105T153913Z.dump`.
- **Follow-up (owner decision, 2026-11-05): its own PR after PR G.**
  - Each user chooses their leverage per subscription, in the panel.
  - The author only recommends one, in a new optional strategy description written in strategy management.
  - The system sets the leverage and isolated margin on the pair before every opening, reads both back, and refuses on a mismatch. On Bybit the margin mode is account-wide, so it is checked, not set.
  - A second open position on the same pair at a different leverage is refused.

## PR H: each user's leverage, set on the venue before every opening

The follow-up of the PNUT incident above, and decision 38. Branch `feat/subscription-leverage`, cut from `b5129b0`. One PR with one migration, `0037`. Strict TDD, owner's word per unit. **Access stays closed (G.D.4 and G.D.5 wait) until this PR is in production**: until then any new user would meet the same 20x default.

### PR H's plan (2026-11-05)

**The map, read at `b5129b0`:**
- **a. Subscriptions.**
  - A subscription's one setting is `allocation_percent` (`0031_subscriptions.py:104-125`, ORM `subscriptions/infrastructure/models.py:70-90`). It is edited by `PATCH /api/subscriptions/{id}` (`subscriptions/infrastructure/router.py:200-216`, `change_share.py:265-297`).
  - The author trades through an ordinary subscription row. `RegisterStrategy` writes it (`author_subscription_adapter.py:27-46`), and the author edits it on the strategy page, not in My subscriptions (`MySubscriptionsPage.tsx:196`).
- **b. The delivery already carries the setting.** It is loaded with its subscription joined (`delivery_adapters.py:28-47`), so a leverage column reaches `Delivery`, `PlaceCommand` (`place_order.py:64-87`) and `OpenOrderSpec` (`execution/application/ports.py:105-132`) with no new query.
- **c. Refusals in `PlaceOrder`.**
  - `build_open_order` runs before any write (`place_order.py:164-173`).
  - `OrderNotPlaceable` is the one definitive refusal there. The reservation is released, the delivery is recorded `REJECTED` with its reason, and it is not retried (`:174-195`).
  - Anything else raised from the build retries.
  - No panel code reads a delivery's `outcome_reason`.
- **d. Venue writes.** Nothing in the repo writes leverage or margin mode today. The adapters read `leverage_for` and size `granted * leverage / mark` (`binance_futures_exchange.py:119-147`, the Bybit twin).
  - Binance already reads `/fapi/v1/symbolConfig` on every opening, weight 5, carrying `leverage` and `marginType`; the parser exists (`read_client.py:296-304`).
  - Bybit reads leverage from `/v5/position/list` (`read_client.py:406-421`). `account_info()` exists but `marginMode` is unparsed (`:479-484`).
  - The signed POST helpers serve only `place_market_order`. The definitive-versus-ambiguous classifier is private to each adapter's `place()` (`binance_futures_exchange.py:285-303`).
- **e. The simulated exchange sizes at a fixed 1x** (`fake_exchange.py:119`, `:187`).
- **f. Strategies have no description.** A description would reach the public page and the preview through `PublicListing` (`performance/application/ports.py:160-171`) and `public_strategies_source.py:67-73`. The author edits it through `PATCH /api/strategies/{id}` (`strategies/infrastructure/router.py:842-880`).
- **g. The holding guard is per strategy** (`holding_guard.py`). Two strategies of one user can each hold the same pair, and the venue nets them, since the account is one-way. This pre-dates PR H; it is recorded here, not fixed.

**The venues, from their documentation (2026-11-05):**
- **Binance.**
  - `POST /fapi/v1/leverage` takes an integer from 1 to the symbol's maximum, weight 1. The maximum is bracket 1's `initialLeverage` in `/fapi/v1/leverageBracket`.
  - `POST /fapi/v1/marginType` takes `ISOLATED` or `CROSSED`, weight 1.
  - Its refusals: `-4046` the type is already set, `-4047` open orders, `-4048` an open position, `-4168` isolated is forbidden under Multi-Assets mode, `-4161` leverage cannot be lowered in isolated with a position open.
  - Sources: [legacy docs, Change Initial Leverage](https://developers.binance.com/legacy-docs/derivatives/usds-margined-futures/trade/rest-api/Change-Initial-Leverage), [Change Margin Type](https://developers.binance.com/legacy-docs/derivatives/usds-margined-futures/trade/rest-api/Change-Margin-Type), [error codes](https://developers.binance.com/docs/derivatives/usds-margined-futures/error-code).
- **Bybit.**
  - `POST /v5/position/set-leverage` takes equal `buyLeverage` and `sellLeverage` in one-way mode; `110043` means unchanged.
  - On a UTA the margin mode is account-wide: `marginMode` of `/v5/account/info`, `ISOLATED_MARGIN`. The per-symbol switch is abandoned for UTA 2.0.
  - Sources: [Set Leverage](https://bybit-exchange.github.io/docs/v5/position/leverage), [Account Info](https://bybit-exchange.github.io/docs/v5/account/account-info), [abandoned cross/isolate](https://bybit-exchange.github.io/docs/v5/abandon/cross-isolate).
- **Not documented, to read live (H.9):**
  - which code each venue answers for a leverage above the symbol's maximum;
  - the spelling of `marginType` in `symbolConfig` for an isolated symbol. Compare it ignoring case until H.9 reads it.

**Decisions stated, not asked:**
- **The leverage is an integer from 1 to 20.** The owner set the cap: "Pongamos x20 tope" (2026-11-05). It replaced 125, the highest per-pair maximum known on Binance, which no document states as a global limit. Binance also gates leverage above 20x behind account checks (`-4202`, `-4203`, `-4205`). A pair's own lower maximum is the venue's to enforce, and its refusal ends the opening.
- **The order of a live opening** is chosen so that no venue setting changes when the opening is refused for another reason:
  1. The adapter sizes at the chosen leverage first.
  2. It runs the step and notional checks.
  3. Only then does it write to the venue.
  - On Binance, it reads `symbolConfig` (already read today). It writes `marginType=ISOLATED` only when the type differs, and `leverage` only when the value differs. After a write it reads `symbolConfig` back. Whatever does not read ISOLATED at the chosen leverage refuses.
  - On Bybit, it reads the account's `marginMode`, and anything but `ISOLATED_MARGIN` refuses. **It is never switched by the system**, because it would change every position in the account. It writes leverage only when the value differs, and reads it back.
- **Weight.** A pair already at the user's settings costs nothing more than today. A change costs at most two writes of weight 1 and one read-back of weight 5.
- **A definitive venue refusal ends the opening**: `LEVERAGE_NOT_APPLIED` or `MARGIN_NOT_ISOLATED`, the reservation released, logged as an ERROR so it reaches Telegram. An ambiguous one (transport, 5xx, 408 or 429) retries, as every other build failure does.
- **A user who holds a pair through one strategy** cannot open it through another at a different leverage: `LEVERAGE_CONFLICT`. Changing the venue's leverage would change the open position under it.
- **A change of a subscription's leverage applies at its next opening.** It changes nothing open.
- **The author's seat** takes its leverage at registration and changes it on the strategy page, like its share.
- **The description is plain text, optional, up to 2,000 characters**, written by the author at creation or on the strategy page. It is shown on the public page and in the preview, and rendered as text, never as HTML or Markdown. Any recommended leverage is written in it; there is no separate field (the owner: "El autor solo recomienda el apalancamiento").
- **Left out:**
  - a panel view of an opening's refusal reason (none exists for any reason today; the ERROR line reaches Telegram);
  - the cross-strategy netting of map g.

**Open, asked one at a time:**
- **H-Q1, answered (owner, 2026-11-05):** "Van con default. En el caso de las estrategias existentes, todas son x2, pero una estrategia nueva debe empezar con x1." `0037` fills every existing subscription with 2.
- **H-Q2, answered by the same words:** every new seat starts at x1, the author's at registration and a subscriber's at subscribe. This reading is stated to the owner, not asked.
- **H-Q3, answered (owner, 2026-11-05):** "Si, las simuladas usan el apalancamineto elegido." A simulated opening sizes at the seat's leverage instead of `FAKE_LEVERAGE = 1`, and records it on the attempt. Simulated trades before the deploy stay at 1x.

**Added by the owner, same message (decision 39):** "el capital que se le asigna a una estrategia nueva es 100%. Cambialo por 0% y que el usuario ponga a mano cuánto quiere usar. No puede olvidarse accidentalmente y que la estrategia opere con 100%, menos si pueden surgir incidentes como el de hoy."
- Today the new-strategy dialog asks no share at all and sends a fixed 100 (`NewStrategyDialog.tsx:17`, `:121`). `RegisterRequest` defaults to 100 when the share is left out (`strategies/infrastructure/router.py:324`). The subscribe form starts at 100 (`SubscribePanel.tsx:19`), and the preview of a user with no seat shows 100 (`strategies/infrastructure/router.py:788-794`).
- Built as follows. Both forms start at 0 % and cannot be sent until the user types a share above 0. `RegisterRequest` requires the share, so leaving it out answers 422. The database keeps refusing 0 (`ck_subscriptions_allocation_percent_range`). The preview of a user with no seat no longer assumes 100.

**Tasks.** Each is a work-unit commit.
- [x] H.1 Migration `0037`, `cc879d4`, with the x20 cap in the next commit.
  - *Built 2026-11-05.* `0037_subscription_leverage.py` and `tests/migrations/test_0037_subscription_leverage.py`, 14 tests.
  - The column keeps a default of 1, so a writer that forgets the leverage opens at the smallest one. The description CHECK trims tabs and line breaks too, not only spaces.
  - RED from mutations: `mutate_h1.ps1`. Before the cap, 10 of 11 were killed. The survivor, the downgrade without its explicit leverage-CHECK drop, is equivalent: PostgreSQL drops a CHECK on a column together with the column.
  - `rehearse_0037.sh` is in the session scratchpad. Its queries were run on a local copy at `0037`, its syntax checked with `bash -n`, and its database swap checked against a fake env file: the copy is `sm_rehearsal_0037` and the rest of the URL is kept. The deploy script is written at H.D.3, once the code is final.
  - Gate at `cc879d4`: ruff 0, mypy 0, pytest exit 0 with no failing test.
  - `subscriptions.leverage` integer, with a CHECK of 1 to 20 and the backfill of H-Q1.
  - `strategies.description` text, nullable, with a CHECK of length ≤ 2,000.
  - The ORM rows for both.
  - Rehearsal and deploy scripts, every query exercised locally.
  - RED from mutations of the CHECKs and the backfill.
- [x] H.2 The leverage of a subscription.
  - `POST /api/subscriptions` takes it, `PATCH /api/subscriptions/{id}` changes it, and the views and the held view carry it.
  - Registration gives the author's seat one.
  - Refusals: a value out of range (422), and a change to an ended subscription (as the share's).
  - *Built 2026-11-05.* `shared/domain/leverage.py` holds `Leverage` (an integer from 1 to `MAX_LEVERAGE` = 20, a `bool` refused), and `NEW_SEAT_LEVERAGE` is one. `Subscription.leverage` defaults to it, so the author's seat written by `RegisterStrategy` starts at one with no change to that path. `change_leverage` is ACTIVE-only, like `change_share`.
  - `POST` takes `leverage` as a strict JSON integer from 1 to 20 and defaults to one when it is not sent. A string, a fraction, `true`, `null` and any value out of range are each answered 422, and nothing is written. The `PATCH` takes a share, a leverage or both; what is not sent is left as it is; a body that names neither is 422; a LEAVING or ENDED subscription is 409 `SUBSCRIPTION_NOT_ACTIVE`; another user's is 404.
  - `ChangeShare` logs a real leverage change after the commit (`leverage changed from x1 to x5`), ids and values only, and only when the value differs.
  - RED was seen on assertions, against stubs that carried the field and did nothing. 24 of 24 mutations were killed (`mutate_h2.ps1`).
  - Gate: ruff 0, mypy 0, pytest exit 0 with no failing test. The panel ignores the new field until H.7.
- [x] H.3 The description.
  - Register and `PATCH /api/strategies/{id}` take it, and `StrategyView` carries it.
  - `PublicListing`, the public body and the preview carry it.
  - It is trimmed, an empty one is stored as none, and one over 2,000 characters is refused.
  - *Built 2026-11-05.* `strategies/domain/description.py`: `description_of` trims the same four characters as the 0037 CHECK, makes a blank one null, counts 2,000 characters after the trim, keeps lines and tabs inside, and refuses any other control character (NUL included, which PostgreSQL would refuse with an unreadable error; not asked for, added so no description answers 500). `Strategy` holds it only in that shape.
  - `PATCH`: a sent description, null included, is a change; a left-out one is not (`model_fields_set` and the `UNCHANGED` sentinel on `UpdateCommand`). Null or blank clears it. A non-string, an over-long or a control-character one answers 422 and changes nothing; an archived strategy's is 409, like every other field.
  - The preview the panel shows before subscribing is the public page's body, so it carries it through `PublicStrategyBody`; the share preview (`SharePreviewBody`) is untouched.
  - RED was seen on assertions, against stubs that carried the field and did nothing. 26 mutations (`mutate_h3.ps1`, `mutate_h3b.ps1`): the first run killed 21 of 24. Two survivors led to changes. `strip()` in place of the four characters survived, so a test now pins that a non-breaking space at the edge is kept, as `btrim` keeps it. `strict=True` on the request field survived because pydantic already refuses a number or a list for a `str`, so it was removed. One mutant did not apply, because the new file is LF; it was rerun, and both reruns were killed.
  - Gate: ruff 0, mypy 0, pytest exit 0 with no failing test.
- [x] H.4 The leverage reaches the order: `Delivery`, then `PlaceCommand`, then `OpenOrderSpec`, the REVERSE's opening included. The simulated exchange sizes at that leverage (H-Q3), and sets nothing, since it has no venue.
  - *Built 2026-11-05.* The delivery query reads `subscriptions.leverage` in the same statement as the share. `Delivery.leverage` and `PlaceCommand.leverage` are required, so a new constructor cannot forget it. `OpenOrderSpec.leverage` defaults to one: `PlaceOrder.place` is its only constructor, and the default keeps the adapters' tests, which name none, at the smallest.
  - A REVERSE's opening and every deferred opening go through `open_now`, which loads the same `Delivery` and builds the same `PlaceCommand`, so they needed no wiring of their own. The `open_now` test pins it.
  - The fake sizes a perpetual at `spec.leverage` (564 granted at 3x and 0.4512 is 3750 STX), and `FAKE_LEVERAGE` is gone. A spot buy takes no leverage. The attempt records what the order carries, through the unchanged `_sizes`.
  - The live adapters receive the leverage and still size at the venue's until H.5 and H.6. Nothing is deployed in between.
  - RED was seen on assertions in the fake, `PlaceOrder`, `ProcessDelivery` and the delivery load. 6 of 6 mutations were killed (`mutate_h4.ps1`).
  - Gate: ruff 0, mypy 0, pytest exit 0 with no failing test.
- [x] H.5 Binance applies it before an opening, in the order above.
  - New `set_leverage` and `set_margin_type` on the trade client, with each refusal code classified.
  - `LeverageNotApplied` is a definitive refusal in `PlaceOrder`.
  - `LEVERAGE_CONFLICT` is checked against the user's open allocations on that pair.
  - `CLAUDE.md` "Open risks" no longer says nothing sets the leverage.
  - *Built 2026-11-05.* The trade client gains `set_leverage` (`POST /fapi/v1/leverage`) and `set_margin_type_isolated` (`POST /fapi/v1/marginType`, `ISOLATED` only). A leverage outside 1..20, or a bool, is refused before any request. -4046 ("No need to change margin type") is not a refusal; every other code is kept on the `BinanceApiError`, so -4047, -4048, -4168 and -4028 reach the adapter intact.
  - `build_open_order`, in order: reads `symbolConfig`, the contract and the mark price; sizes at the CHOSEN leverage and runs the step and tradable checks, so an unplaceable opening writes nothing; returns with no write when the pair is already isolated (compared ignoring case, until H.9 reads the real spelling) at the chosen leverage; otherwise reads the position; sets ISOLATED first, then the leverage; reads the config back; builds the order at the chosen leverage.
  - Three refusals, all `OpeningSettingRefused` with a `reason_code`: `LEVERAGE_NOT_APPLIED` (refused or read back otherwise), `MARGIN_NOT_ISOLATED` (refused, read back otherwise, or held on cross margin), `LEVERAGE_CONFLICT`. A write the venue answered definitively becomes the refusal with the venue's code in its message; an unknown outcome (-1001, -1007, 408, 429, a 5xx, no answer) propagates unchanged and the job retries, and the retry reads the config again.
  - `PlaceOrder` releases the reservation and rejects the delivery under the exception's `reason_code` on one commit, as for an unplaceable size, but logs at ERROR, so it reaches Telegram.
  - **Deviation from the plan.** The conflict is checked against the venue's position on the pair, read only when a write is needed, not against the user's open allocations in the ledger. The venue's position is what a new leverage would change, whatever opened it: another strategy of the same user, a position opened by hand, or one the ledger has not settled yet. The ledger cannot see the last two.
  - `test_real_adapters_size_from_the_venue_price.py`: its Binance pair is now ISOLATED at 3x and its spec asks 3x, so the test stays about the price and writes nothing. `test_a_grant_too_small_to_reach_one_step_is_refused_by_name` now asks 1x itself, since the venue's leverage no longer sizes.
  - RED was seen on assertions, against stubs: exception classes caught and ignored in `PlaceOrder`, and trade client methods that did nothing. 30 of 30 mutations were killed (`mutate_h5.ps1`), after a test for an unknown outcome on the margin write was added.
  - Gate: ruff 0, mypy 0, pytest exit 0 with no failing test.
- [x] H.6 Bybit, the same way: `marginMode` parsed and required to be `ISOLATED_MARGIN`, leverage set when it differs and read back.
  - *Built 2026-11-05.* The read client gains `position_for` (the symbol's record from `/v5/position/list`, matched by symbol, flat or not, so one read gives the leverage and whether the pair is held) and `margin_mode` (`marginMode` of `/v5/account/info`, a non-empty string or a loud failure). The trade client gains `set_leverage` (`POST /v5/position/set-leverage`, equal `buyLeverage` and `sellLeverage`, 1..20 checked before any request, 110043 "leverage not modified" not a refusal, every other code kept). The read client still has no writing method.
  - `build_open_order`, in order: reads the position record, the contract and the mark price; sizes at the chosen leverage and runs the step and tradable checks; reads the account's margin mode on EVERY opening and refuses anything but `ISOLATED_MARGIN`, compared exactly (`MARGIN_NOT_ISOLATED`, never switched); returns when the symbol already holds the chosen leverage; refuses a held symbol at another leverage (`LEVERAGE_CONFLICT`); sets the leverage and reads the position back (`LEVERAGE_NOT_APPLIED` on a definitive refusal or a mismatch; an unknown outcome propagates and retries).
  - Fixtures that served a trimmed position record (`{"symbol", "leverage"}`) now serve a complete flat one plus the account's margin mode, at the leverage their spec asks, so they write nothing: `test_trade_client_catalogue.py`, `test_real_adapters_size_from_the_venue_price.py`.
  - **Found while building H.6, and a defect H.5 left:** `check_binance_round_trip.py`, `check_bybit_round_trip.py` and `check_bybit_sizing.py` build through the production adapters with no leverage in the spec, so 1x. Since H.5 the Binance preview would have set the pair to 1x and isolated before printing "PREVIEW ONLY. Nothing was placed, nothing was changed". The three now ask for the leverage the pair already holds (`scripts/held_leverage.py`, refused when it is not a whole number from 1 to 20), so they keep sizing at the account's leverage and their previews write nothing. The Binance round trip also refuses a pair not already ISOLATED, rather than letting the adapter switch it. `mypy` on `check_bybit_round_trip.py` still reports two `list-item` errors at the `BybitBalanceReader` pool tuples, which were already there and are outside the gate.
  - RED was seen on assertions, against stubs (a positional `position_for`, an empty `margin_mode`, a `set_leverage` that did nothing, a `held_leverage` that always answered 1x). 23 of 23 mutations were killed (`mutate_h6.ps1`).
  - Gate: ruff 0, mypy 0, pytest exit 0 with no failing test.
- [x] H.7 The panel's leverage.
  - A control in the subscribe form, in My subscriptions beside the share, on the author's seat on the strategy page, and in the new-strategy dialog.
  - The control is built like the share's `ShareSlider` (`ShareSlider.tsx`: a text field plus a range): a slider from 1 to 20 in steps of 1, beside a numeric field, with the value read as "x5". The owner asked for a slider like the pool share's (2026-11-05).
  - EN/ES copy, including what it means ("applies at the next opening; the system sets it on the exchange").
  - *Built 2026-11-05.* **Backend gap closed first.** `POST /strategies` took no leverage, so every new strategy's author seat was born at 1x although the plan says the seat takes its leverage at registration. It now takes an optional `leverage` (strict JSON integer 1..20, default 1); `RegisterCommand.leverage` reaches `AuthorSubscriptionPort.subscribe_author`. 7 of 7 mutations killed (`mutate_h7a.ps1`).
  - **Panel** (written by a Sonnet writer, reviewed by the parent): `leverage-value.ts` (`parseLeverage`: a trimmed whole number 1..20, "05" reads 5; `leveragePosition`), `LeverageSlider.tsx` (the field with an "x" before the number, a 1..20 range, stops at x5, x10, x15, x20 in fixed classes a test holds to the position function; it reuses `ShareSlider`'s `RANGE_CLASS`), `useLeverageDraft.ts`, and `SubscriptionLeverageEditor.tsx` with its own Save, which sends only `{"leverage": n}` and is read-only when archived or not ACTIVE. The editor sits after `PoolShareEditor` on the author's seat and in My subscriptions; the subscribe form and the new-strategy dialog start at x1 and send `leverage` as a number. `isSubscription` requires an integer `leverage`. The My subscriptions button now reads "Change share and leverage", since it opens both.
  - 14 of 14 mutations killed (`mutate_h7b.ps1`, `mutate_h7c.ps1`). The first run left one survivor: the new-strategy dialog's guard against a submit by Enter with an invalid leverage. Its test asserted nothing was posted synchronously, before a request could have left; it now waits a task first, and the mutant dies.
  - Gate: backend ruff 0, mypy 0, pytest exit 0 with no failing test; frontend lint 0, vitest 121 files and 3,273 tests passed.
- [x] H.8 The panel's description: written at creation, edited on the strategy page, shown on the public page above its figures. EN/ES.
  - *Built 2026-11-05* (written by a Sonnet writer, reviewed by the parent). `description-value.ts` reads a description as the server does: it trims only space, tab, CR and LF (a non-breaking space is kept, as `btrim` keeps it), a blank one is nothing, and the length is counted in code points, so 2,000 passes and 2,001 is refused. The control-character rule is left to the server's 422.
  - `DescriptionField` (textarea, label, info hint, "n / 2000" counter) is shared by the new-strategy dialog and `StrategyDescriptionEditor`. The dialog sends `description` as typed only when it is not blank, and refuses to submit over the limit, by button or by Enter. The editor, on the author's strategy page after the leverage, has its own Save. It compares what the server would keep with what it keeps, sends only `{"description": text}` or `null` when blank, and is read-only on an archived strategy. Its refusals: 422, 409 and 404 in words.
  - The public page, which is also the preview before subscribing, shows it between the header and the figures as plain text with its line breaks (`whitespace-pre-line`). Nothing is drawn when it is null. A test shows `<b>`, `<img onerror>`, `<script>`, Markdown and a bare URL literally and finds no element made from them.
  - Both shape guards, the author's strategy and the public body, now require `description` (a string or null). The API restarts before the panel moves, so a deployed panel never reads a body without it. `description: null` was added to the strategy fixtures of 19 test files.
  - 15 of 15 mutations killed (`mutate_h8.ps1`).
  - Gate: frontend lint 0, vitest 124 files and 3,321 tests passed; no backend change.
- [x] H.10 Decision 39, the share is typed by hand.
  - The new-strategy dialog gets a share field and the subscribe form starts at 0 %. Neither can be sent with 0.
  - `RegisterRequest` requires `allocation_percent`.
  - The preview with no seat and no share asked shows no sizing instead of 100 %.
  - EN/ES copy.
  - *Built 2026-11-06.* Backend by the parent, panel by a Sonnet writer reviewed by the parent.
  - Backend: `RegisterRequest.allocation_percent` has no default, so leaving it out answers 422 naming the field and writes no row. `PreviewShare.preview` takes `share: Decimal | None`; with `None` there is no `exact`, while the balance and the hundred steps are still served. The route hands `None` when the caller holds no live seat and asked no share. Every test registration body now carries a share.
  - Panel: the subscribe form and the new-strategy dialog both start at "0". Untouched, the field shows a neutral hint (`strategies.detail.share.startHint`) and is not marked invalid; after any edit the usual refusal applies. Neither form sends while the share is invalid, by button or by Enter. The dialog's field (`useShareInput`, no preview: there is no strategy yet) sits before the leverage and sends the share as typed.
  - Found by the writer: the panel's preview validator refused `exact: null` beside a balance, which would have read "The amount could not be loaded" at the untouched start. It now accepts it.
  - RED on assertions: 422 (`assert 201 == 422`), the two no-seat preview tests (`exact` was the full share), the use case (after a stub, so it failed on the assertion, not a `TypeError`), and the panel's start states and POST body.
  - Mutations: backend 4 of 4 killed (`mutate_h10be.ps1`), panel 13 of 13 (`mutate_h10fe.ps1`).
  - Gate: backend ruff 0, mypy 0, pytest 0 with nothing failing; frontend lint 0, vitest 124 files and 3,328 tests passed.
- [x] H.9 Owner-run, before the deploy: a probe that reads `symbolConfig` for one isolated pair (the spelling of `marginType`). It also asks for a leverage above one pair's maximum while flat on it, so the venue refuses with the code H.5 classifies.
  - *Probe written 2026-11-06:* `backend/scripts/check_binance_leverage.py --user-email <e-mail> --symbol <PAIR> [--confirm]`. The preview reads `symbolConfig`, `leverageBracket` and the position, and sends nothing. `--confirm` sends one `POST /fapi/v1/leverage` at the pair's maximum plus one, only on a flat pair, prints the code and what `_is_definitive_rejection` makes of it, and reads the settings back. If Binance ever accepted it, the original leverage is written back and the run fails.
  - `bracket_max` and `spelling_verdict` are tested in `tests/scripts/test_check_binance_leverage.py`; 6 of 6 mutations killed (`mutate_h9.ps1`).
  - *Run by the owner on the VPS 2026-11-06*, on AAVEUSDT (isolated, 2x, flat, maximum 75x), piped over ssh onto the deployed checkout (`5a7a9a3` let it run without H.5's `_is_isolated`):
    - `symbolConfig` answers a list and spells `"marginType": "ISOLATED"`, upper case, as `_is_isolated` expects.
    - Asking 76x answered HTTP 400, `code=-4028`, "Leverage 76 is not valid". `_is_definitive_rejection` reads it as a refusal, so an over-maximum leverage ends the opening as LEVERAGE_NOT_APPLIED and is never retried.
    - Read back: still ISOLATED at 2x; nothing changed.

**Delivery.**
- [x] H.D.1 Gate (backend and frontend), and an independent verifier over the whole PR. It names items 1 (`0037`), 3 (the subscribe and strategy contracts) and the venue writes of a live opening.
  - *2026-11-06.* Gate before the verifier: backend ruff 0, mypy 0, pytest 0 with nothing failing; frontend lint 0, vitest 124 files and 3,328 tests.
  - Opus verifier over `b5129b0..56adf0d`: migration 0037, Bybit writes (H.6), order flow and sizing (H.4), API contracts and panel pass; probes write nothing in preview. One blocker:
  - **B1, fixed.** Binance answers a rate limit as HTTP 429 with `code=-1003`, and an overload as 503 with `-1008`; the transport copies the code onto the error and `_is_definitive_rejection` reads the code first, so a throttled setting write ended the opening as LEVERAGE_NOT_APPLIED or MARGIN_NOT_ISOLATED instead of retrying, against decision 38. The tests had built the 429 with no code. Now `_is_definitive_setting_refusal` reads 408, 429 and any 5xx as unknown whatever the code, and both setting writes use it. The order path (`place`) keeps its classifier, as at baseline. 5 of 5 mutations killed (`mutate_hd1.ps1`).
  - Advisories:
    - A1, fixed on the owner's word ("Dale, como decis"): `StrategyDetailPage.tsx:86-88` gave three sibling editors the same `key={subject.id}`; React warned of duplicate keys, and a change of `:strategyId` while the page stays mounted with the next strategy cached left the previous strategy's share and leverage editors on screen. The three now sit in one keyed `Fragment`. A test visits B, then A, then the cached B and finds one share field and one leverage slider; it failed with two share fields before the fix.
    - A2: the deployed panel's `isSharePreview` refuses `exact: null`, so between the API deploy and the panel move a user with no seat sees "The amount could not be loaded" on the subscribe form. Subscribing still works.
    - A3, fixed on the owner's word: a successful margin or leverage write on a user's account logged nothing; only refusals logged. Each adapter now logs one INFO line once the venue's read-back confirms the write, naming the pair, the state before and after, and the order's client id ("Binance AAVEUSDT set to ISOLATED at 5x, was CROSSED at 20x, before order …"; "Bybit BTCUSDT leverage set from 20x to 3x before order …"). Nothing is logged when nothing was written or the read-back refuses. 6 of 6 mutations killed (`mutate_a3.ps1`).
    - A4: the read-back right after a successful write has not been seen live; a lagging read would refuse that one opening definitively.
    - A5: a Bybit 403 "access too frequent" (no retCode) on set-leverage is definitive; a retry inside the ban would fail too.
- [x] H.D.2 Push and PR (owner's word), merge (owner), with a merge commit.
  - Pushed and opened as #95 on the owner's "Si, push y PR", 22 commits over `b5129b0`. Merged by the owner on 2026-11-06 as `3d09d1f`.
- [x] H.D.3 Rehearse `0037` on a fresh backup, deploy, then pps.6 after the API.
  - Deployed by the owner on 2026-11-06 in three scripts piped over ssh (session scratchpad: `deploy_pr95_1_rehearse.sh`, `deploy_pr95_2_api.sh`, `deploy_pr95_3_panel.sh`).
  - Rehearsal: pulled as `strategy` to `3d09d1f726e2`, then backed up and restored into `sm_rehearsal_0037`. On that copy, `0036 -> 0037` turned all 7 subscriptions (4 ACTIVE, 3 ENDED) to leverage 2, left all 7 strategies without a description, created both CHECKs and kept a column default of 1. The downgrade dropped the column and the re-upgrade restored it. The copy was dropped.
  - API: a fresh backup `pre-0037-deploy-20261106T151320Z.dump`, then production upgraded from `0036` to `0037` with the same counts. Both services restarted and read `active`, and no ERROR or Traceback line followed.
  - Then pps.6: the assistant built the bundle from a detached worktree of `origin/main` at `3d09d1f726e2`, 22 entries, SHA-256 `c453fc67269fda74db9647475aaa14debb2c3e1e5a51756864c0cceb12d9c2cc`. The owner's block printed `OK`, `readable`, and `bundle` and `checkout` both at `3d09d1f726e2`.
  - Not yet seen in production: a live opening that sets a pair's leverage (verifier A4), and its INFO line.

## Decision 40: same-day trades that follow each other compound (PR #96)

- [x] D40.1 `combine_by_day` in `performance/domain/curve.py` (overlapping trades summed, later ones compounded, each group's factor floored at 0, one group keeps its plain sum), for the panel and the public record; RED on assertions for six rules, 9 of 9 mutations killed, gates green. Commit `c07fe41`.
- [x] D40.2 Pushed and opened as #96 on the owner's "Si, por favor", 5 commits over `3d09d1f` (PR H's delivery record, the owner's panel requests, the measuring script and its result, decision 40). Merged by the owner on 2026-11-06 as `f8c73e8`.
- [x] D40.3 Deployed by the owner on 2026-11-06 with two scripts piped over ssh (session scratchpad: `deploy_pr96_1_api.sh`, `deploy_pr96_2_panel.sh`). No migration.
  - API: pulled as `strategy` to `f8c73e8000ed`; database and code head both `0037`; both services restarted and read `active`, and no ERROR or Traceback line followed.
  - Then pps.6: the assistant built the bundle from a detached worktree of `origin/main` at `f8c73e8000ed`, SHA-256 `b2f4dc79d32f7aa89c1fb95be160ab7b824dacc36a08e50eff030c1a02c1cd32`. The owner's block printed `OK`, `readable`, and `bundle` and `checkout` both at `f8c73e8000ed`.

## PR I: the panel requests after PR H

The owner's requests under "Panel requests pending", built together on the owner's "Dale, vamos con panel" (2026-11-06). Decisions 36 and 37 and the four asks of 2026-11-06, plus the icons and the red Leave of 2026-11-02. No migration. Owner's word per unit; the owner reads the running panel before the PR.

### PR I's plan (2026-11-06)

- [x] I.1 Backend, decision 36: the pool and strategy performance responses carry `origin`, the UTC date the first trade with a return opened (null with no such trade). `curve.py` reads it from the same trades the curve uses; the router serves it beside `curve`. Rule 7 unchanged: one pool, one origin.
  - Done: `PoolPerformance.origin` from the trades with a return (a trade with no capital at open never sets it), the opening's UTC day; `PerformanceBody.origin`, so the strategy body carries it too. 5 of 5 mutations killed, gate green.
- [x] I.2 Panel, decision 36 and the All dates: `ReturnChart` draws a 0 point on `origin` before the first close, for All and for any window that reaches back to it (a window starting later rebases as today). The All range labels its start date and today, and between them month, week or day steps chosen from the span, under the same minimum label gap. When the first trade opened and closed on one day, the line starts at 0 on that day.
  - Done (inline): `withOrigin` and `spanTicks` in `shared/charts/scale.ts`; `ReturnChart` takes `origin`, and every range, All included, now runs to today. All names its start and today, with days up to 14 days of span, weeks up to 90, month starts beyond; a date between keeps 40 units from either end and 28 from the previous. Six tests that read All as ending on the last close now read it on that day. `origin` is optional in the panel's type and refused when it is not a string or null, so a panel served before the API restarts still reads. 16 of 16 mutations killed (two survivors first, closed by a test each).
- [x] I.3 Backend: the share preview takes an optional `leverage` (1-20, the `Leverage` value object) and serves the notional beside the amount (`amount * leverage`, in `Decimal`), so the panel never multiplies money. Without it, `notional` is null.
  - Done: `Leverage.notional(margin)` in `shared/domain/leverage.py`, the route's optional `leverage` query (1 to `MAX_LEVERAGE`, refused with the redacted 422), `exact.notional` in the body. Steps carry no notional. 6 of 6 mutations killed, gate green.
- [x] I.4 Panel, compact settings (strategy page, My subscriptions, subscribe form, new-strategy dialog): the input and its Save on one row, Save as wide as its own text needs and the input taking the width left (owner, 2026-11-06: "Prefiero que el boton de Save ocupe el espacio necesario para mostrarse bien, y el resto el input"); every Save says only "Save" (icon kept; the busy and done states shortened the same way); the amount line summarized to the margin asked and, when leverage is above 1, the notional.
  - Done 5d7d2bd (Sonnet writer, reviewed): `ShareSlider`/`LeverageSlider` take an `action` beside the field (`min-w-0 flex-1` field, `shrink-0` Save); share, leverage, description and pairs Saves say only "Save" ("Saving…"/"Saved" were already short); each editor's section has its own accessible name. The amount line reads `Margin: X` and, above 1x, `· Notional: Y` from the server's `exact.notional` (the preview asks `leverage` only above 1x; the seat's leverage in the editor, the form's in Subscribe). Description and pairs keep their layout (a textarea and a chip selector, not a field and a button); the new-strategy dialog has no Save or amount line. 4 mutations killed.
- [x] I.5 Panel: http and https URLs in a strategy's description become links (`target="_blank"`, `rel="noopener noreferrer"`), everywhere the description is shown as text. The description stays plain text: no HTML, no Markdown, no other scheme. One pure helper in `shared/lib` with its tests (a URL at the end of a sentence keeps its period outside the link).
  - Done (Sonnet writer, reviewed): `shared/lib/linkify.ts` and `shared/ui/LinkifiedText.tsx`; the public page is the only read-only render of a description (the strategy page shows the editor). An older test that asserted no link for an `https` URL now uses `javascript:` and `www.`. 6 of 6 mutations killed.
- [x] I.6 Panel: /strategies nav says "My strategies" instead of "Authored", and each of its three buttons gets an icon; Leave in My subscriptions is red like Delete key, through one shared danger style both use.
  - Done (Sonnet writer, reviewed): `shared/ui/danger-control.ts` (`DANGER_CONTROL`, Delete key's classes unchanged), Leave with `LogOut`; nav icons `Bookmark`, `Compass`, `FolderOpen`; `es.json` already read "Mis estrategias". 5 of 5 mutations killed.
- [x] I.7 Panel, decision 37: an exchange tab shows only where its user has a key, an open position, or an active strategy or subscription. Pools alone no longer make a tab. `ExchangeTabs` and `useExchangeScope` read one shared rule; while a source is still loading, no tab is dropped.
  - Done (Sonnet writer, reviewed): `shared/scope/running-exchanges.ts` (`runningExchanges`, `distinctExchanges` moved there). Active: a STORED key, any open position, an enabled unarchived strategy, an ACTIVE subscription. A source that has not succeeded keeps the pool list. ~~Assumption: when nothing runs anywhere, the pool list stays.~~ The owner refused it (decision 37, amended 2026-11-06): nothing running shows no tab, and Pionex never gets a tab until its API trading is confirmed. Reopened as I.7b. Open positions are read by `useQuery` on the same key as `useOpenPositions`, held back until there is a pool, so a page with no exchange still asks for nothing. 7 of 7 mutations killed.
- [x] I.7b Panel, decision 37 amended: no fallback to the pool list when nothing runs (no tab at all), and `pionex` never gets a tab. While a source is still loading, the pool list still stays, as before.
  - Done (inline): `NEVER_A_TAB` in `running-exchanges.ts` filters `pionex` before anything else, the fallback is gone. RED seen on assertions for both (6 tests); Overview, Settings and tab tests that drew Pionex tabs now use Bybit or an unknown `okx`. An open Pionex position would have no tab; none is expected, since Pionex trades no futures over the API. Gates green (lint, 3406 frontend tests; `test_one_phrase_per_fact` timed out once under load and passes alone in under 1 s).
- [x] I.8 Panel: one `Tooltip` in `shared/ui` (shown on hover and on keyboard focus, the icon keeping its accessible name), and icons in place of the labels the owner named: on Explore items the age, the closed trades and the return; on the owner's strategy rows the days active, closed trades and subscribers. Money, the mode and anything easy to misread stay as text.
  - Done (Sonnet writer, reviewed, then adjusted inline): `shared/ui/Tooltip.tsx` (`Tooltip` on hover and focus, hidden on leave, blur and Escape, `aria-describedby` while shown; `IconTip` keeps the label as the icon's accessible name and is not described by a tip that repeats it). Icons: Explore and the public page (`PublicFigures` is shared) age, closed trades, return; the owner's rows days active, closed trades, subscribers. Kept in sight: a baseline's lower bound (`≥3`) and the live count (`3 · 2 live`). Money and the never-enabled and Archived words stay text. 4 writer mutations plus 3 REDs inline; gates green, 3433 frontend tests.
- Owner's review of the running panel (2026-11-06), verbatim:
  - "al mover el slider o actualizar el share en el input, el texto de Margin: x USDT se actualiza al instante, pero al cambiar el apalancamiento, hasta no darle a Save no se actualiza el Notional. Si consideras que asi es mejor, dejalo. Sino, que se actualicen por igual."
  - "En /explore, 'trading it live' podría tener un icono de persona/s con tooltip que lo aclare. Age podría ser un calendario en lugar de un reloj. El reloj da sensacición de corto plazo, y un calendario a lo mejor lo representaría mejor."
  - "Cuando entro a una estrategia a la que estoy suscrito, se podría gestionar allí mismo también el share y apalancamiento. Actualmente manda a gestionarlo de nuevo a /strategies con el botón de Change share and leverage. La seccion Subscribe se podría reemplazar por los settings cuando uno está suscrito más el boton de Leave. Si considera que es mejor poder cambiar la configuracion de las estrategias en ambos lugares, lo hacemos así. Sino que se gestione entrando directamente a cada estrategia."
  - "La vista de una estrategia como suscriptor no me muestra su historial ficticio que arme una curva, el mes a mes, by pair, etc que debería poder ver un suscriptor para evaluar si le interesa, tanto en suscripciones como en /explore. A lo mejor no tienen, pero no lo puedo corroborar"
- [x] I.9 Panel: the notional follows the leverage being chosen, before Save, as the margin follows the share (one leverage draft shared by the share line and the leverage editor).
  - Done (Sonnet writer, reviewed): `SeatSettings` owns the one `useLeverageDraft` and hands its value to `PoolShareEditor` (`leverage` prop; an invalid draft reads as the saved leverage) and the draft itself to `SubscriptionLeverageEditor` (`draft` prop). Both Saves send only their own field. Used on the author's strategy page and the public page.
- [x] I.10 Panel: on Explore and the public page, "trading it live" becomes a people icon with its tooltip, and the age icon a calendar instead of a clock.
  - Done (inline): `Users` and `Calendar` in `PublicFigures`; the label reads "people trading it live" / "personas operándola en vivo" so the tip says who. RED on assertions (2 tests); lint and the Explore, public page and i18n tests green.
- [x] I.11 Panel: a subscriber manages a seat on the strategy's own page: the Subscribe section is replaced, while subscribed, by the share and leverage settings and Leave. My subscriptions lists each seat's share and leverage as read-only text with a link to the strategy, and Leave (assistant's call, given to it by the owner: one place to edit, so the list stays a summary).
  - Done (Sonnet writer, reviewed): `SubscribePanel` swaps the Subscribe section for "Your subscription" (`SeatSettings` and a red Leave through `LeaveDialog`) while the reader holds a seat that is not theirs as author; a LEAVING seat reads only. My subscriptions shows share and leverage as text, the link and Leave; the "Change share and leverage" toggle and both editors are gone. 4 mutations killed. **Advisory:** a seat on a strategy that has since gone private links to a page that 404s, so it can only Leave from the list, not change its share or leverage. Closed by J.1.
- [x] I.12 The strategy's record (curve, month by month, by pair) on the public page: today the public body serves only the figures (age, trades, return, capital), so there is nothing to draw. Who sees it, owner (2026-11-06): "Lo debe poder ver cualquiera para analizar si le interesa entrar. Aunque no me queda claro cómo vería un usuario su propio rendimiento desde que está suscrito y el rendimiento histórico (las reales del autor) en una misma." Proposed: two views of one report on the public page, "Strategy record" (anyone) and "My results" (a seat's own fills, default for a subscriber), never blended into one chart, the record marking the day the reader's seat began. The owner: "Dale, si" (2026-11-06).
  - [x] I.12a Backend: `GET /api/public/strategies/{id}/record`, anonymous like the public list, read from the author's real fills only (rehearsal never counts, as `public_record.py`): `origin`, `curve` (date, daily return, cumulative, drawdown), `monthly`, `ranges` (return and trade count per range, no money), `by_pair` (trades, wins, win rate, compounded return per pair, no money), `closed_trade_count`, `max_drawdown`. Each trade's return is the record's (unleveraged price move, before fees), combined by day as decision 40. 404 where the public body would 404. No PnL, no amount: the author's money stays private.
    - Done 3b9f658 (Sonnet writer, reviewed): `build_record_report` in `public_record.py`, `range_window` shared with `range_summary`, `read_public_record.py`, the route in `public_strategies_router.py` (signed in like every public route; 404 also when a figure does not fit the wire, with a WARNING). A pair's win is a return above 0. Route guard list updated. 6 mutations killed; gates green.
  - [x] I.12b Panel: on the public page, one report (curve, month by month, by pair) with two views: "Strategy record" (anyone, I.12a) and "My results" (only with a seat, the default then, read from `GET /api/performance/strategy/{id}`), never one chart for both; the record marks the day the seat began.
    - Done (Sonnet writer, reviewed): `StrategyReportViews` on the public page (selector only with a seat, "My results" first, one chart at a time), `PublicRecordReport` (no money; return line with the unleveraged, before-fees disclosure), `ReturnChart` `marker` for the seat's start inside the window, `PairStatsTable` without a currency for the record, `fetchPublicRecord` guard refusing any money key. 5 mutations killed; gates green, 3478 frontend tests.
- [x] I.13 Panel, owner's ask on reading I.12b (2026-11-06): "Así como Strategy settings en cualquiera de las estrategias propias está en un aside, lo pondría igual en estrategias suscritas (seccion Your subcription) y estrategias que el usuario explora (seccion Subscribe)... En el caso de mobile, si puede quedar abajo, como en las estrategias propias".
  - Done (inline): the public page is the own strategy's two-column grid (`lg:grid-cols-[minmax(0,1fr)_25rem]`); Subscribe and Your subscription are an `aside` in the right column, framed as Strategy settings, after the record in reading order so a phone stacks it last. 1 mutation killed (aside moved first); gates green, 3480 frontend tests.
- [x] I.14 Panel, owner's ask (2026-11-06): "en las tarjetas de My subscription mostraría lo mismo que muestran las tarjetas de Explore, con la diferencia de que age sea el tiempo que se estuvo suscrito, y que adicionalmente muestre el share del pool y leverage. Sacar el boton de Leave, que se gestiona dentro de cada estrategia. Ademas ajustar los iconos con un color mas claro... Hacerlos un poco más grandes que el (i) y centrarlos con el valor que encabezan. Cambiar 'no real trades yet' por algo más breve. Lo mismo con por ejemplo 6 dias de age. Cambiar por 6d. No se como aparezca si tuviese por ejemplo 1 año y 4 meses, pero proponeme algo y te confirmo".
  - Done (inline): My subscriptions cards draw Explore's figures from the public list (`StrategyFigures`, split out of `PublicFigures`), the age counted from the seat's `created_at`, then share (`30%`) and leverage (`x4`) under ChartPie and Gauge; no Leave (its dialog tests moved to the public page, where the one Leave lives); a strategy off the public list draws the reader's figures only, and a failed public read says so. `IconTip` is `text-ink-2` at 18 px (the info glyph is grey at 16 px); each figure centres its icon over its value. Ages are short in their two largest units (`age-text.ts`): `6d`, `4mo 12d`, `1y 4mo` (ES `6d`, `4m 12d`, `1a 4m`), the long form a proposal awaiting the owner's word. "no real trade yet" is now "not yet" / "aún no". 6 mutations killed; gates green, 3502 frontend tests.
  - Owner, same day: "mencionar 'capital' me lleva a ajustarlo para que esté acorde a los iconos, con el tamaño de fuente, weight y color. Ademas agregarle tooltip que aclare que es el capital con el que opera la estrategia". The capital is headed by a Wallet `IconTip` named "capital the strategy trades with" / "capital con el que opera la estrategia"; its (i) stays on the public page. A seat on a PRIVATE strategy ("Test new strategy" in the review data) draws only the reader's figures, by design: the public figures exist only for a public strategy. 3503 frontend tests.
  - Owner, on the short ages: "Dejá mo en inglés." The long form (`4mo 12d`, `1y 4mo`; ES `4m 12d`, `1a 4m`) is confirmed.
- [x] I.15 Panel, owner's asks (2026-11-06): "el icono de closed trades y su valor esta bien, pero los dos items siguientes textuales no tienen el mismo tamaño y se desalinean verticalmente. Reemplazar por iconos con tooltip..."; "el switch para desactivar una estrategia debería pedir confirmación... Activarla también debería pedir confirmación."; "el botón para pasar de LIVE a DRY RUN y viceversa, tiene una flechita como si fuera un desplegable... Me gustaría que despiegue las dos opciones que se pueden elegir."; "las pestañas de Binance, Bybit, etc, podrían aparecer un poco más a la derecha, separandose un poco mas del brand, para que o bien coincida con el espacio que ocupa el side bar en desktop, o tenga ese espacio más un padding adicional".
  - Done (inline): My strategies' PnL and return are Coins and TrendingUp `IconTip`s, each centred over its value like the trades. `useEnableQuestion` (`EnableDialog.tsx`) is the one way to enable or disable: the row's switch and the page's button both ask first, the state asked for fixed when the question opens, a refusal shown inside it; disabling says a position already open still closes (only `allocate_capital` reads `enabled`). The mode badge is a drop-down (`ModeMenu`: Live and Simulation as `menuitemradio`, the one in force checked; the other one opens the existing `ModeDialog`; closes on a pick, Escape, outside press or a second click). From lg the brand's box is 9.5rem, so the tabs start at 13.25rem, just past the side bar (13rem + 4px) and without the page's padding; the owner first read 15.25rem as too far ("Hace que empiece donde empieza el contenido de la página, el ancho del side bar, y unos 2-4 pixeles adicionales, pero sin el padding de la página"). 4 mutations killed; gates green, 3515 frontend tests.
- [x] I.D Gate, owner reads the running panel (fixture config), push and PR on the owner's word, deploy (API restart, then pps.6).
  - Pushed and opened as #97 on the owner's "Dale, avisame cuando esté el PR". Merged by the owner on 2026-11-06 as `e6cffca` (parents `f8c73e8`, `19cc94a`).
  - Deployed by the owner, no migration: pulled as `strategy`, both services restarted and read `active`. Then pps.6: the assistant built the bundle from a detached worktree of `origin/main` at `e6cffca3d560`, SHA-256 `028bbe726ff601820337b2f58205dbc89a42ed4eabe4f0dc193e245e6c125574`. The owner's block printed `OK`, `readable`, and `bundle` and `checkout` both at `e6cffca3d560`.
  - The block's readability check names a wrong path first (`/opt/strategy-manager/panel/current`) and falls back through `||` to the right one, so `readable` was read from `/opt/strategy-manager-panel/current`. Harmless; the next block names only the right path.

Units are about 100-250 lines each and depend on nothing but I.1 before I.2 and I.3 before I.4.

## PR J: a seat keeps its page when its strategy turns private

Closes I.11's advisory. Owner (2026-11-07), on subscribers who can no longer change their share and leverage once the strategy goes private: "Con respecto a que los suscriptores ya no puedan cambiar share y apalancamiento, creo que habría que ver otra forma." Then: "Si alguien entró, se debe poder quedar." and "Mientras arrancá por el arreglo del asiento". Sharing a private strategy by link or invitation code is a separate design, with its own decision and migration; it is not part of this PR. No migration.

- [x] J.1 Backend: `GET /api/public/strategies/{id}` and `/{id}/record` answer a strategy turned private to a reader who holds a live seat on it (`ACTIVE` or `LEAVING`) and is not its author, so the seat is managed where it always was, on the public page (decision 21: a strategy turned private keeps its subscribers). Everything else stays the one 404: an ended seat, a seat on another strategy, somebody else's seat, an archived strategy (archiving ends every seat), an author with no name, and the author's own seat (the author has their own page). The list never shows a private strategy, and open positions still link through `LISTED`.
  - Done: `PublicStrategiesSourcePort.listing(strategy_id, reader_id)`; `READABLE` (not archived, a named author) split out of `LISTED`; `listing` reads `READABLE` and `PUBLIC or _held_by(reader)`; both routes take the signed-in reader. The panel needed no change: the page shows "Your subscription" whenever the reader holds a seat. RED on assertions (404 where 200 was expected, both routes). 6 hand mutations killed (no reader filter, no author exclusion, no strategy correlation, ENDED counted, LEAVING not counted, `READABLE` dropped). The cross-user sweep's private probes still hold: B holds no seat on the private strategy.
- [x] J.2 Panel, from the verifier's advisory 2: after Leave on a strategy turned private, the refetch answers 404 while the query keeps its old data, so the page drew the strategy with a Subscribe the API refuses. A 404 now wins over the data read before it, and the page says the strategy is not on the list. Stale comments on the page and on `fetchPublicStrategy` name the seat exception.
  - Done (inline): RED on an assertion (no "not on the public list" text after Leave), then green; lint green, 3516 frontend tests.
- [x] J.D Gate, independent verifier (Risk: item 2, the route now answers a private strategy to someone other than its author), push and PR on the owner's word, deploy (API restart, then pps.6 for J.2).
  - Opus verifier 2026-11-07 on 67fd499: no blockers; every J.1 statement holds, the SQL compiles to the intended correlated EXISTS, the list and the open-positions link are unchanged, PATCH share and leverage never read visibility. Advisories: (1) after going private, the author's return, record, live count and `capital` (which includes the author's own live seat) keep updating for the remaining seat-holders: the same fields they read while it was public; owner (2026-11-07): "Que sigan viendo todo"; (2) the stale page after Leave: J.2; (3) stale comments: J.2; (4) "Explore" back-link leads to a list without the strategy, and open positions do not link a private strategy's page for its subscriber (`LISTED`), by design; (5) no test seeds a PRIVATE archived strategy with a live seat (archiving ends every seat, so low risk). In production the query still retries a 404 three times before the page says so (the app's default); the test harness does not retry.
  - Pushed and opened as #98 on the owner's "Que sigan viendo todo, dale push y PR", 3 commits over `e6cffca`. Merged by the owner on 2026-11-07 as `4011f91` (parents `e6cffca`, `d9ab628`).
  - Deployed by the owner on 2026-11-07, no migration: pulled as `strategy` (`e6cffca..4011f91`, 12 files), both services restarted and read `active`. Then pps.6: the assistant built the bundle from a detached worktree of `origin/main` at `4011f9111840`, 22 entries, SHA-256 `90973ba574507427d02bb022ed4516d4f7495eac055510f9f1351ba8a5334f36`. The owner's block printed `OK`, `readable`, and `bundle` and `checkout` both at `4011f9111840`.
  - Not yet seen in production: a seat-holder opening the page of a strategy turned private.

## PR K: sharing a strategy off the public list (decision 41)

Decision 41: a strategy off Explore can be shared by a link or by single-use invitation codes, managed from the own strategy's aside, and whoever entered stays. Owner (2026-11-07): "Dale, escribilo como decisión 41". One migration, `0038`. Owner's word per unit; the owner reads the running panel before the PR. Risk: item 2 (who may read a strategy and subscribe to it) and item 1 (migration), so an independent verifier closes the PR and the migration is rehearsed on a fresh backup.

- [x] K.1 Migration `0038`: `strategies.visibility` CHECK gains `LINK`; `strategies.share_token` (nullable, unique, set exactly when `visibility = 'LINK'`, enforced by a CHECK); table `invite_codes` (`id`, `strategy_id`, `code_hash` unique, `created_at`, `expires_at`, `revoked_at`, `redeemed_by`, `redeemed_at`, `subscription_id`). Existing rows keep their visibility and get no token. Downgrade refuses while a strategy is `LINK` or a code exists, rather than dropping them silently. Rehearsal script as `rehearse_0037.sh`.
  - Done (inline): `0038_strategy_sharing.py`, `StrategyRow.share_token` and its CHECKs, `InviteCodeRow` in `subscriptions/infrastructure/models.py`. Constraints: `ck_strategies_share_token_iff_link`, `ck_strategies_share_token_shape` (43 URL-safe characters, as `secrets.token_urlsafe(32)` writes), `ux_strategies_share_token`; `ck_invite_codes_code_hash_shape` (SHA-256 lower-case hex), `ck_invite_codes_hint_shape` (four Crockford base32 characters), `ck_invite_codes_expiry_after_creation`, `ck_invite_codes_redemption_whole`, `ck_invite_codes_revoked_or_redeemed`, `ux_invite_codes_code_hash`, `ux_invite_codes_subscription`. `fk_invite_codes_strategy` and `fk_invite_codes_subscription` cascade. RED against an empty `0038` (most on the constraint name, the rest on the missing column or table), 42 tests green. 11 hand mutations of the migration killed, and 3 of the history count (codes blocking, never counted, the log line); backend gate green.
  - The references guard caught the new key into `strategies`: `StrategyHistory` gains `invite_codes`, counted by `StrategyHistoryAdapter` and named in the delete's INFO line, and never blocking (it cascades, as subscriptions do). The `HAS_HISTORY` body gains the `invite_codes` key; the panel reads only the kinds it lists, so it is unaffected.
- [x] K.2 Domain: `Visibility.LINK`; one rule for who may read a strategy's page and who may subscribe, replacing `offered_to_others`' two-way answer: PUBLIC to anyone, LINK to a holder of the current token, PRIVATE to a holder of a live code; a live seat reads in every mode (J.1). The code value object: format (`XXXX-XXXX`, Crockford base32, case and the dash ignored on input), hash, 7-day expiry.
  - Done (inline): `Visibility.LINK`; `Entry` (NONE, LINK, CODE) and `offered_to(visibility, author_named=, entry=)` in `strategies/domain/strategy.py`, replacing `offered_to_others`, whose two callers (subscribe, the share preview) pass `Entry.NONE` until K.4. A live code also opens a LINK strategy (assistant's call: it was made for that strategy, and the link would admit the same person; owner, 2026-11-07: "Entiendo que es una forma opcional de entrar a una estrategia en modo link, por lo que me parece bien"). `share_token.py` (`new_share_token`, `is_share_token`); `invite_code.py` (`InviteCode.generate/parse/display/hash/hint`, Crockford look-alikes I/L to 1 and O to 0, `repr` hides the code; `IssuedCode.new/is_live`, 7 days, live strictly before expiry). The plain SHA-256 is kept, as decision 41 says; the module names the offline-search tradeoff. Until K.3 the API refuses `LINK` on create and PATCH with a 422 (`WritableVisibility`), since a LINK strategy needs a token. RED on assertions against stubs; 14 hand mutations killed; backend gate green.
- [x] K.3 Author routes: change the visibility (a new token on entering LINK, none on leaving it, no seat touched); `POST` a code (shown once, only while PRIVATE), list the unused live ones (no code, only an id, a short hint and the expiry), revoke one. Author only, 404 to anyone else as every author route.
  - Done (inline): the link's token lives on the domain `Strategy` (`share_token`, `repr` hides it, held exactly while LINK as the CHECK holds it) and changes only through `Strategy.with_visibility`: entering LINK makes one, staying keeps it, leaving drops it, so a leaked link dies with the change. Register and PATCH both go through it; the repository reads and writes it; `StrategyView.share_token` shows it to the author only (every author route reads through `AuthorStrategyRepository`). `WritableVisibility` is gone: the API takes LINK. Turning PUBLIC or LINK asks the author's name (`NEEDS_A_NAMED_AUTHOR`), on turning only, so a form that resends the visibility it holds still saves. `AuthorHasNoDisplayName`'s message now says "offered to others". Codes: `strategies/application/invite_codes.py` (`IssueInviteCode` reads the row `FOR UPDATE`, refuses `STRATEGY_ARCHIVED`, `STRATEGY_NOT_PRIVATE`, `AUTHOR_HAS_NO_DISPLAY_NAME`; `ListInviteCodes`; `RevokeInviteCode`, one `UPDATE ... RETURNING` on a live code of this strategy, else 404), `InviteCodesPort` and `SqlAlchemyInviteCodes`. Routes `POST` (201, `no-store`, `{id, code, hint, expires_at}`), `GET` (`{id, hint, expires_at}`, oldest first) and `DELETE .../invite-codes/{code_id}` (204, row kept). One INFO line per issue and revoke naming the strategy, the code's id and its hint, never the code or its hash. Revoking takes no visibility or archive check: it only takes access away. Codes made while PRIVATE stay live if the strategy turns LINK or PUBLIC (a code opens LINK too, K.2); the author can still revoke them. Cross-user sweep: three new probes with a seeded live code of A's (its id and hint are traces); route guard list updated; the secret sweep seeds a live code and walks the three routes. RED on assertions (26); 27 hand mutations killed (one survivor, resending the visibility held, killed by a test added for it); backend gate green.
- [x] K.4 Reader routes: the public page and record read with `?link=` or `?code=` as well as by seat; subscribe takes `link_token` or `invite_code`, and a code is spent in the seat's own transaction (single use under a row lock, refused once expired, revoked or spent). Failed code attempts are counted per user and refused past a limit, with a log line (assumption to confirm in the unit: 10 per hour). Every refusal answers the one 404 or one refusal code that names no other user. Cross-user sweep probes for every new route.
  - Done (inline): the page, the record and the share preview take `?link=` and `?code=`; `POST /api/subscriptions` takes `link_token` and `invite_code` (each at most 64 and 32 characters, longer is a 422 that echoes nothing). The link is tried first, the code only when nothing else opens the strategy, so a code is never read, counted or spent where it is not needed (a PUBLIC strategy, a valid link, a live seat). The link opens a LINK strategy to its current token only (compared in constant time in Python, by equality in SQL); a live code of THIS strategy opens it if LINK or PRIVATE; neither opens anything of an author with no name. `CheckInviteCode` (`strategies/application/code_entry.py`) runs on a second session of the request (`Depends(get_session, use_cache=False)`), so the failures it writes commit even when the request rolls back; it holds `pg_advisory_xact_lock(hashtext('invite-code-attempts'), hashtext(user))` for the check, so one user's checks run one at a time and the limit is exact. A wrong, malformed or other strategy's code answers the same 404 as no strategy; a dead one answers 410 `INVITE_CODE_NOT_LIVE` with `reason` `EXPIRED`, `REVOKED` or `SPENT` (what happened beats the clock), naming nobody; past the limit 429 `TOO_MANY_CODE_ATTEMPTS`, the code unread and nothing written. Each failure (wrong, malformed or dead) writes one row of new table `invite_code_attempts` (migration `0039`: who and when, cascades with the user, index on `(user_id, attempted_at)`) and prunes that user's rows older than the hour, and logs one WARNING naming the user, the strategy, the outcome and the count, never the code; a refusal at the limit logs one WARNING and writes nothing. The limit is `MAX_FAILED_ATTEMPTS = 10` in `ATTEMPT_WINDOW = 1 hour` (the plan's assumption; owner, 2026-11-07: "10 por hora está bien"). The window slides: a user at the limit gets one attempt back as each failure turns an hour old, and a refusal writes nothing, so trying while refused never extends the wait. Subscribing writes the seat, then spends the code in one `UPDATE ... WHERE live` under its row lock, re-read there, so two holders of one code make one seat; a code gone meanwhile refuses with 410 and the seat rolls back. No route was added, so the cross-user sweep needs no new probe; the public source docstring and the routes say how a link or code opens a page. RED on assertions (domain and the integration cases, 48 once the two guard tests were added); 36 hand mutations killed, none survived (two equivalent mutants left out and named here: a link opening PRIVATE, which holds no token by the 0038 CHECK, and the rollback on a dead code, which the closing session does anyway); backend gate green.
- [x] K.5 Panel, own strategy's aside: one visibility selector (Public · With link · Private); With link shows the link and a copy button; Private shows "Create code", the new code once with copy, and the unused codes with expiry and an ✕. EN/ES.
  - Done (inline): `Visibility` gains `LINK` and `Strategy` gains `share_token` (the guard requires the key, a string or null). The select offers Private · With link · Public, most closed first so the default stays first, with a link icon for With link; the new-strategy dialog offers the same three. The hint says what each one means, and "choose your name first" now speaks of a strategy offered to others. `StrategySharing` sits in the aside right after the seat's settings (the share stays the first setting, as pinned): a LINK strategy shows `<origin>/strategies/explore/<id>?link=<token>` with Copy link; a PRIVATE one shows Create code, the new code once (`gcTime: 0`, put away with Done, never shown again), and the unused codes as `····-XXXX` with their expiry in UTC, each with an ✕ that revokes it. Creating and revoking read the list again whatever the outcome. An archived strategy creates no code and still revokes. Refusals in words: not private, no name, archived, gone, failed; a revoke's 404 says the code was already used, expired or revoked. API client: `fetchInviteCodes`, `issueInviteCode` (a body without a code is an error that never echoes it), `revokeInviteCode`, with their hooks under `['strategy', id, 'invite-codes']`. 34 hand mutations, 32 killed; the 2 survivors are equivalent under the `share_token` CHECK (only a LINK strategy holds a token): showing the link for any strategy with a token, and showing codes for any non-public one.
- [x] K.6 Panel, reader: "I have a code" on Explore opens the strategy's page; a link opens it too; Subscribe sends the link or the code. A spent, expired or revoked code says so in words. EN/ES.
  - Done (inline). **A route K.4 did not have:** a code alone names no strategy, and the page needs one, so `POST /api/public/invite-codes/lookup` (`{code}` in the body, never the path, so no access log keeps it) answers `{strategy_id}`. A code's hash is unique across every strategy (`ux_invite_codes_code_hash`). It spends nothing and counts like every other code: `CheckInviteCode.locate` shares the lock, the limit and the failure writing with `check` (`_admit`, `_settle`); the port gains `locate(code_hash)`. Wrong or malformed is a 404, dead a 410 with its reason that names no strategy, the limit a 429, longer than 32 a 422 that counts nothing. Added to the guarded routes, the cross-user sweep (B holding A's real code learns its strategy, on purpose, and nothing of A's changes; `shows` may now name an id) and the secret sweep (a real seeded code, answered 200). Panel: Explore always shows "I have a code" above the list, whatever its state; it opens a form, looks the code up (trimmed), and opens `/strategies/explore/<id>?code=<code>`. The page reads `?link=` and `?code=` (an empty one is none) into an `Entry` context that its read, its record, the share preview and Subscribe take (`link_token`, `invite_code`); keys gain the entry only when there is one. A dead code, too many wrong codes, and a link or code that opens nothing say so in words on the page, on Explore and on Subscribe, and a refusal wins over a strategy read before it. EN/ES with usted. Backend: 8 hand mutations, all killed. Panel: 25 hand mutations, 24 killed; the survivor drops the entry from the query keys, whose only effect is a stale 404 shown for a moment before the refetch when the same page is opened again with a code. Gate: ruff, mypy, frontend lint and 3585 tests green; one backend failure, `test_a_job_whose_user_cannot_be_read_waits_for_every_job_before_it` (G.7 lanes, nothing K.6 touches), seen once while the frontend suite ran beside it and passing alone three times out of three: a flake under load, for K.D to look at.
- [x] K.D Gate, independent verifier, owner reads the running panel (fixture config), push and PR on the owner's word, rehearse `0038` and `0039` (K.4 added the attempts table), deploy (migration, API restart, then pps.6).
  - **The G.7 lanes flake** (`test_a_job_whose_user_cannot_be_read_waits_for_every_job_before_it`) was the test's, not the claim's: the claim orders by `(run_after, id)`, and Python 3.12's wall clock ticks every 15.6 ms on Windows, so the continuation could share a delivery's `run_after` and, with a smaller random id, come before it. Forcing that tie reproduced `{None, delivery}` every time. The test now moves the deliveries a second earlier (6b954e8). The VPS clock is not that coarse; production orders simultaneous jobs arbitrarily, as designed.
  - **Opus verifier, 2026-11-07, three blockers**, fixed in one batch:
    - **B1, codes and link tokens in the access log.** `access_log.py` redacted only `secret|token|api_key|password`, and the page, the record and the share preview take `?link=` and `?code=` on every read. `link` and `code` are now redacted (2 mutations, killed).
    - **B2, the code check starved the pool.** It drew a second pooled connection while its request held one, so as many concurrent code-bearing requests as connections waited for each other until the pool timed out: 500s, and a stall for every request beside them, the webhook's included. Reproduced with a pool of 2 and two requests: `[500, 500]` on the page, the record, the preview and subscribe. The check now runs on a `NullPool` engine of the request session's own database (built once per database, holding no connection), so no request waits for a pooled connection while holding one; the pool's size still bounds how many are open. Tests that override `get_session` reach their own database unchanged. 1 mutation (back to the request's pool), killed.
    - **B3, one visit with a dead code counted four failures.** The panel's `QueryClient` keeps the library's three retries and its refetch on focus, and every refused read is one of the reader's ten an hour. Reads that carry an entry now retry only what may pass (`retryTransient`, moved to `client.ts`), are not read again on focus once refused, and the share preview stops polling a refused code; reads with no entry keep the client's defaults. `renderAt` takes the client's query defaults, so the tests run on the library's retries. 5 mutations, killed.
    - Advisories: A1 (offline search is about 2^20 with the hint beside the hash) and A4 (the share preview's docstring said it writes nothing) corrected in the docstrings. Open, for the owner: A2 the lookup names an archived strategy or one whose author has no name, and the page then says the code opens nothing; A3 no log line for the loser of a spend race, a successful redemption, or turning, rotating or killing a link; A5 the author's link token is not marked `no-store`. A6 was the lanes hang, which came from two runs sharing `strategy_manager_test` at once.
    - Gate after the batch: ruff, mypy, backend suite, frontend lint and 3590 frontend tests green.
    - **Recheck (801123c): B1, B2 and B3 closed, and one new blocker in B2's fix.** The lookup holds no connection of its request (`current_user` commits it back), and a check waits on its user's lock holding its connection, so with no pool the checks were unbounded: 20 concurrent lookups held 20 connections against a pool of 2, and about 100 would use up PostgreSQL's. A new finding earns no second correction by the verification bound; the owner authorized one (2026-11-08, "Dale, hacé la segunda corrección").
    - **Second correction.** The checks have a pool of their own, `CHECK_POOL_SIZE` = 3 with no overflow and `CHECK_POOL_TIMEOUT_SECONDS` = 10 (`PoolBounds` in `shared/db.py`): a check holding one never waits for the request's pool, and a flood of checks fails only checks. The pool is built once per request engine (`check_engine_for`, a `WeakKeyDictionary`) and closed with it (`engine_disposed`), so a test's pool never outlives its event loop. 5 mutations, killed.
    - **Recheck (92c3165): closed.** The verifier's probe read 3 connections waiting on the lock, not 20; 30 concurrent page reads with a code on a request pool of 5 answered 10 404s and 20 429s, the limit exactly, no 500 and no stall. Advisory: a check that waits the 10 s for a slot (a stalled database, a held lock) answers a generic 500 while its request holds its main-pool connection; a 503 with a WARNING line would say why.
    - **Owner's reading of the panel (2026-11-08):** "Revisado. Todo correcto, aunque casi no veo la seccion nueva del link. La pondría inmediatamente debajo del titulo y selector de visibilidad de la estrategia, por encima de la seccion de sliders de share y leverage. Además lo compactaría dejando el input de link sin salto de linea y con overflow horizontal y el botón Copiar enlace, simplemente con un icono de copy, y a lo sumo un tooltip de Copiar, y llevaría el texto 'Quien abra este enlace ve la estrategia...' a un (i) al lado de 'Enlace de la estrategia'. Lo mismo con el texto en modo privado de 'Cada código permite...' en su (i) al lado de 'Códigos de invitacion'." Done: the sharing block sits right under the settings' heading and visibility, above the share and the leverage (it supersedes K.5's "the share stays first", which still holds for a public strategy); the link is a read-only one-line input that scrolls; Copy link is an icon with its name and tip, "Copied" once done, the failure in words; both hints behind an information button beside their titles (`linkInfo`, `codesInfo`, EN/ES). `Tooltip` gains `tabbable` so a tip around a button is one keyboard stop. 8 mutations, killed; frontend lint and 3595 tests green.
    - Left as advisories: a refused read is asked again when the network comes back (`refetchOnReconnect`), and a 5xx or lost answer is retried, so a counted failure whose answer was lost can count up to twice more.
    - **Delivered 2026-11-08.** PR #99 merged with a merge commit, `e4e28ce` (parents `4011f91` and `9ca8ee1`). Rehearsal on a copy restored from `/var/backups/strategy-manager/pre-0039-rehearsal-20261108T223812Z.dump`: 0037 to 0039 clean; strategies PRIVATE 3 and PUBLIC 4, none with a token; 8 sharing constraints; 0 codes and 0 attempts; a LINK strategy with no token refused; downgrade to 0037 left no `share_token` column and no sharing table, and the upgrade back reached 0039. Production: backup `pre-0039-deploy-20261108T223927Z.dump`, migrated 0037 to 0039 with the same counts, `strategy-api` and `strategy-worker` active, no ERROR or Traceback line since the restart. Panel (pps.6): built from a detached worktree of `origin/main` at `e4e28ce657d8`, 22 entries, SHA-256 `44b0a3a1b04d03c6b65541a009615bd83b009761e4d488c621665decf6ac4d20`; the owner's block printed `OK`, `readable`, and bundle and checkout `e4e28ce657d8`. Not yet seen in production: a link or a code used by a real reader.

## PR L: the panel asks after PR K

The owner's list of 2026-11-08, sent once PR K was deployed ("Son varias cosas, y las fui redactando a medida que surgían. Si alguna se contradice o ya se hizo, avisame o ignorala"). Branch `feat/panel-after-k`, cut from `docs/pr-k-delivery` (`main` plus PR K's delivery record). No migration. The owner reads the running panel (fixture config) before the PR.

### The owner's asks (2026-11-08), verbatim

> En strategies/explore dentro de una estrategia el info (i) de rendimiento se repite en la tarjeta con iconos y en el encabezado del chart <p> 'return All x% · caída máxima x% (i)', y dicen lo mismo. Mantener el del encabezado en <p>
>
> Todos los tooltip se deben emprolijar, deben comenzar con mayuscula y ser concisos y precisos.
>
> Se puede agregar al chart de las curvas un hover que muestre el return del momento a la altura donde esté el puntero?
> Además un efecto degradé debajo de la curva con su color. Es bastante común en charts hoy en día y queda muy bien. Así como hay grilla horizontal, agregar verticales, para referencia visual del tiempo. También suavizar las curvas un poco. En definitiva, modernizar un poco el chart.
>
> Filtrar estrategias desc por antiguedad, closed trades, return, personas suscritas o capital, segun seleccione el usuario. Por defecto return/contribution to the pool. Volver a hacer clic pasa de desc a asc.
> Los mismos iconos que usamos en las tarjetas de strategy, usarlos en overview para available, return, PnL y deepest, y pasar lo textual a tooltips. Lo mismo en stratgies/explore/id y strategies/id.
> El icono de deepest puede ser el opuesto a return, un trending hacia abajo. Agregar el deepest en las tarjetas de estrategias al lado de return.
> Cuando aún no hay historial de return, en lugar del valor 'not yet' prefiero el mismo carácter que usa capital '—' cuando no hay capital.
> Añadir icono de winrate a las tarjetas de estrategia donde tenga sentido, luego de lo return y deepest o antes.
> En mobile las filas solo tienen dos iconos, ocupan mucho el espacio vertical, y se podría reducir permitiendo  por ejemplo 4 iconos por fila. Y en el caso de mobile, usar place-ítems: center para el grid.
>
> En el encabezado de overview y estrategias, cuando esté seleccionado All en el rango de tiempo, no aclarar en aporte al pool el tiempo. Solo si está seleccionado last 7D, 30D, etc.
>
> Que las tarjetas de estrategia sean enteramente cliqueables para entrar a la vista de la estrategia
> Las tarjetas en /authored que tengan el mismo formato de iconos que las de suscripciones y /explore, con su switch al final.
> No vi si en las tarjetas de suscripciones aparecen las tags tipo 'AAVEUSDT · LONG · Live' como veo en /authored. Pero si ya aparecen, dejarlo así. En /explore también deberían aparecer. Las tarjetas deberían ser iguales en las tres secciones, con la diferencia de qué se muestra. Lo que varía sería el share, apalancamiento y el switch según la vista.
> Una estrategia de otro autor no muestra si esta activada o desactivada. Mostrar tanto en las tarjetas como en la vista de la estrategia. Actualmente solo lo muestra la vista de una estrategia propia.
>
> Que el input de código en /explore siga el mismo formato del div de New strategy en /authored.
> En /authored remover el div que muestra 'Open: 0 Orders in flight: 0 Last read: 22:56:29 UTC Read again'.
> Para mi, cas asi nunca es relevante.
>
> En Strategy settings, aside sección description, poner en la misma fila el <p> de '0 / 2000' en el mismo div de 'Description (i)' y el botón Save que pase de estar de la izquierda a la derecha.
>
> En Strategy settings, aside sección allowed pairs, poner en la misma fila el input de search symbol y su botón Save. Y pasar el texto 'Removing a pair stops new entries...' a un (i) al lado de Allowed pairs.
> Además las etiquetas de los pares añadidos, que pasen al lado de <legend> Allowed pairs, para ocupar menos espacio vertical.
>
> Poner los botones de Disable strategy y Archive en la misma fila, con Archive en rojo, que se dividan por igual el ancho, y Enable history debajo. El texto 'Archive is available once...' se quita, y se deja como tooltip al pasar el mouse por encima del botón Archive si no está habilitado.
>
> Cuando una estrategia solo tiene un par con trades, la sección By pair solo repite información que ya se muestra en el encabezado de la vista. Solo mostrarla si hay más de un par con trades.
>
> Cambiar botones de guardar y copiar texto solo por su icono con tooltip. Lo mismo con otros botones como delete.
>
> El botón de Leave en el aside de una estrategia suscrita, debe ocupar todo el ancho disponible, como lo hacen los botones de disable strategy y archive.
>
> Compactar el gap entre secciones del aside. El multiplicador actual es .gap-5. Con * 2 se puede reducir bastante y sigue quedando bien.

### What the code says about them (read-only map, 2026-11-08)

- Nothing on the list is already done. Two asks supersede earlier owner words: icon-only Save and Copy replace I.4's "Save" labels, and "—" replaces I.14's "not yet".
- **The "AAVEUSDT · LONG · Live" line is not a strategy tag.** It is the author's open positions (`Mark` chips through `OpenMarks`), so it appears only on the author's own cards. On Explore it would show anyone a stranger's open positions as they stand; on My subscriptions the natural reading is the reader's own seat's positions. Settled by the owner in L.4: only the reader's own.
- The Overview has no "contribution to the pool" label: it says "PnL {{range}}" and "return {{range}}". The strategy page says "contribution to the pool {{range}}", the public record "return {{range}}". All four drop the range under All.
- Data the lists lack: Explore has no total subscribers, no max drawdown, no win rate and no enabled state; My strategies has no creation date, and its return and closed trades come from each card's own performance read; My subscriptions takes its figures from the public list, so a seat on a LINK or PRIVATE strategy has none.
- Win rate exists only per pair (`by_pair.py`, `public_record.py`); a strategy's rate is the sum of wins over the sum of closed trades.
- The chart's straight segments are deliberate ("smoothing would invent values"). A monotone cubic (Fritsch-Carlson) passes through every real point and never overshoots between two of them, so it invents no high and no low.

### PR L's plan (2026-11-08)

- [x] L.1 Backend: the public body (`PublicStrategyBody`, list and page) gains `subscribers` (ACTIVE seats, the author counted, as `StrategyView`), `max_drawdown` and `win_rate` (from the record's real fills, as the record route; null with no closed trade) and `enabled`; the held seat view gains `enabled`; `StrategyView` gains `created_at`. Added fields only; no money is added to a public body.
  - Owner (2026-11-08), on `enabled` leaving the public body (F.4 had kept it out as a setting): "Si la estrategia esta habilitada o no, debería ser del conocimiento de sus suscriptores. Si una estrategia está habilitada, o no le aporta información al suscriptor para saber si se adhiere o no. Si la monitorea y constantemente está deshabilitada, probablemente la evitaría o se desuscribiría".
  - Days active on every card (owner, 2026-11-08). Asked whether to show the days active beside the age, after reading that they are different figures (the age counts from `created_at`, the days active add up the enabled stretches of the enablement log, so a strategy made 90 days ago and disabled for 60 reads 90 and 30): "Dale, mostrá los dos en todas las tarjetas". So the public body and the held seat view also carry the strategy's `uptime` (seconds, first enable, baseline), the same shape `StrategyView` carries, and every card shows the calendar (age, or time subscribed on My subscriptions) and the clock (days active).
  - Done 32e470e and 0cd3feb (inline): `PublicListing` gains `enabled` and `subscribers` (an ACTIVE-seat count subquery), `PublicRecord` gains `max_drawdown` and `win_rate` (a return of 0 is no win, null with no closed trade); the source's `enablement` reads the log through `SqlAlchemyEnablementLog.list_for_many`, and `ReadPublicStrategies` (now given a clock) adds the uptime; the held view reads the log for its seats; `UptimeView` has its own module. The leak test had `enabled` among the private words (F.4) and lets it out now; the public read is five statements, one more, whatever the length. RED on assertions (KeyError on the missing fields for some); 12 mutations killed, one survivor first (a win rate of one win in two cannot tell wins from losses), closed with four trades. Gates green.
- [x] L.2 Panel, chart: monotone smoothing for the curve and the drawdown edge, a gradient under the curve in its colour, vertical grid lines at the existing date ticks, and a hover that marks the nearest day and shows its date and cumulative return (pointer; the figures stay readable without it).
  - Done 7849f45 (Sonnet writer, reviewed): monotone cubic segments (`M … C …`) for the curve and the drawdown edge in `scale.ts`, a level tangent at each local extreme; `return-fill` under the curve, `text-gain` stops, opacity 0 at the waterline, per-chart `useId`; `vgridline` at each date label; pointer move, down, leave and cancel draw `hover-guide`, `hover-dot` and `hover-label` ("Jul 3 · +30%"), `touch-pan-y` keeps vertical scrolling. Four older tests counted vertices as `L` and now count `M`, `L` and `C`. 15 of 16 mutations killed, the survivor equivalent.
- [x] L.3 Panel, one card for the three lists: the whole card opens the strategy (the switch and any other control keep their own action), the same figure row everywhere (age or time subscribed, days active, closed trades, return, deepest with TrendingDown, win rate, subscribers, capital), "—" where there is no figure yet, four icons a row on a phone with centred items; what varies is the share and leverage (My subscriptions) and the switch, last (My strategies). Another author's strategy shows enabled or disabled on its card and its page.
  - Done 2f108d3 (two Sonnet writers, the first cut by the usage limit and not resumed; reviewed): `StrategyCard` with the title link stretched over the card and every control `relative z-10`, `CARD_GRID` four a row and centred on a phone, eight from `lg`; `card-figures.ts` builds Explore's and the seats' figures from the public body and My strategies' from the per-card report (`authoredFigures`: the win rate is the sum of wins over the sum of trades across pairs), PnL kept on that card only; an enabled pill for another author's strategy; "—" where there is no figure, `noRealTrade` removed. The clock's tooltip keeps the old "active N days" wording until L.9's tooltip pass.
- [x] L.4 Panel, the open-position chips: only the reader's own. My subscriptions shows the reader's seat's open positions on each card, as My strategies shows the author's; Explore shows none. Owner (2026-11-08), asked whether Explore shows an author's open positions: "Solo las mías, en Explore no".
  - Done 2f108d3: `OpenMarks` takes the card's id, name and exchange; My subscriptions draws the reader's own positions on the strategy; Explore draws none and asks for no positions (a test pins both).
- [x] L.5 Panel, sorting: one sort control on the three lists (age, closed trades, return, subscribers, capital), descending first, a second click ascending, return by default (contribution to the pool on My strategies, the record's return elsewhere). A strategy with no figure for the key sorts last both ways.
  - Done 2f108d3: `card-sort.ts` (a missing figure last both ways, ties in the list's order) and `SortControl` (`aria-pressed`, direction arrow); My strategies sorts on the same reports the cards draw through `useStrategiesPerformance`, which shares `useStrategyPerformance`'s query key. Also from L.9: "I have a code" is a green button opening a dialog like New strategy, and `OpenStateLine` is deleted with its test. About 50 mutations killed across the unit (three survivors first, each closed by a new test). Gates: lint clean, 140 files and 3722 frontend tests green.
- [x] L.6 Panel, figures as icons: the Overview's available, PnL, return and deepest, the strategy page's ledger and the public record line become icons with their words in tooltips; the public page's figure card loses its return (i), the record line keeps it; the range is said only when it is not All.
  - Done (Sonnet writer, reviewed): `LedgerLine` is a `<dl>` of `Figure`s, Wallet, Coins, TrendingUp and TrendingDown with the words in their tooltips, on the Overview and the strategy page; the public record line draws return and deepest the same way and keeps the only (i), the figure card's gone. `rangeLabel` picks `pnl`/`return`/`contribution`/`recordReturn` under All and their `*Range` keys otherwise. The public page's header carries the enabled pill (`EnabledBadge`, shared with the card).
- [x] L.7 Panel, the aside: Description's counter on its heading's row and Save on the right; Allowed pairs' chips beside the legend, the search and Save on one row, the hint behind an (i); Disable and Archive side by side at equal width, Archive red, its disabled reason as Archive's tooltip, Enable history below; Leave full width; the section gap `gap-2` in both asides.
  - Done c75cf1b with L.8 (Sonnet writer, reviewed): the counter on the heading's row in `DescriptionField` (the new-strategy dialog too), Save right-aligned; `PairSelector` names its fieldset through `aria-labelledby` on a span (a `<legend>` cannot share a wrapping row with chips), with (i) and chips in that row and the search beside Save; Disable and Archive `flex-1` in one row, Archive `DANGER_CONTROL`, its reason a tooltip on a focusable wrapper and a hidden `aria-describedby` text; Leave `w-full`; `gap-2`. The Archive tip is still the long `archive.disabledHint`, left for L.9's tooltip pass.
- [x] L.8 Panel, buttons: Save, Copy and Delete become icon buttons with a tooltip (the saving and saved states kept, as icon and tooltip), on the pattern of PR K's copy icon. A dialog's own confirm button keeps its words.
  - Done c75cf1b: `shared/ui/IconButton` (44 px, tooltip that does not also describe, tones neutral, primary, danger; `name` when the accessible name says more than the tip, as "Delete key Bybit"); `StatusButton` `iconOnly` (spinner while busy, check once saved, the shown text as name and tip). Save in seven editors, Copy, Delete strategy and Delete key; the sharing block's copy icon reuses it. 40 mutations killed (one survivor first, closed). Gates: lint clean, 136 files and 3639 frontend tests green.
- [x] L.9 Panel, the rest: "I have a code" on Explore takes New strategy's form, a button in the same place opening a dialog with the input; My strategies drops the open-state line (Open, Orders in flight, Last read, Read again; the Discrepancies page keeps its own); By pair shows only with more than one pair with trades; every tooltip starts with a capital and says one thing briefly, EN and ES.
  - Done: By pair only when more than one pair has a trade (its empty state and key gone); every tooltip capitalised and short, pinned by `shared/i18n/tooltips.test.ts` (the clock reads "Days active" with the count in the value; Archive's reason "Disable it and close its positions first" / "Primero desactívela y cierre sus posiciones"; capital "Capital it trades with" / "Capital con el que opera", kept from I.14's ask); dead keys removed (`positions.state.figures`, `notShown`, `archived`, `strategies.row.active*`, the unused `strategies.subscriptions.*` tips). Native `title=` hints outside the tooltip components were not part of the pass. 10 mutations killed. Gates: lint clean, 141 files and 3776 frontend tests green.
- [x] L.D Gate, owner reads the running panel (fixture config), push and PR on the owner's word, deploy (API restart, then pps.6).
  - Review fixes before the owner's read (`c1509df`): on lg the card's figures share one row of equal columns (`lg:grid-flow-col lg:auto-cols-fr`, values `lg:whitespace-nowrap`), where eight fixed columns wrapped PnL and share onto a second row; the curve's gradient spans the curve's own height, from its farthest point to the waterline, where anchored to the plot's edges it was nearly invisible. 6 hand mutations killed; 3777 frontend tests, lint green. Render notes: Edge headless has a minimum width near 500 px, so phones are read at 500 px.
  - **Delivered 2026-11-09.** PR #100 merged with a merge commit, `ce9b81e` (parents `e4e28ce` and `f18b905`). No migration: production stayed at 0039. API: the deploy script pulled as `strategy`, read the checkout `ce9b81e8bc70` and alembic `0039`, restarted `strategy-api` and `strategy-worker`, both `active`, no ERROR or Traceback line since the restart. Panel (pps.6): built from a detached worktree of `origin/main` at `ce9b81e8bc70`, 22 entries, SHA-256 `e92025760a3a0254584a4e50e321a8ce32ee588c8260bfc640df0efb75b0f96f`; the owner's block printed `OK`, `readable`, and bundle and checkout `ce9b81e8bc70`. Not yet seen in production: the new public body fields read by the panel, and a live setting write with its INFO line (A4 of H.D.1).

L.1 comes before L.3, L.5 and L.6's figures; the rest depend on nothing else.

### The owner's second round (2026-11-09), verbatim

Sent after reading the running panel.

> En los charts, apicarle un degradé también a la curva de deepest hacia 0.
>
> El botón de Delete strategy es una excepción de los botones de solo icono. Ponerle su texto Delete strategy, así el botón cobra importancia.
>
> En overview, prefiero que el icono de Saldo disponible esté a la izquierda del saldo. El resto de iconos encima de su valor está bien, porque son valores con fuente más chica y los iconos quedan bien alineados entre sí.
> El texto de 'El saldo está desactualizado...' que aparezca dentro de un (i) a la derecha del saldo, solo si está desactualizado.
>
> Los tooltips de 'Deepest drawdown', cambiarlos por solo 'Drawdown'.
>
> En las tarjetas e estrategias, agregar align ítems center al contenedor del titulo de la estrategia y su tag enabled para que no se desalineen.
>
> Que otro icono para Win rate me podes proponer?
>
> En la vista de una estrategia:
> - el numero de PnL tiene fuente más grande que la de aporte al pool y cauda máxima.
> Además el tooltip muestra PnL 1A, Aporte al pool 1A. No se que es 1A, pero aparece en todas las estrategias.
>
> - que no son propias, la sección con antigüedad, operaciones cerradas, retorno, gente y capital, se podría unificar con los iconos y valores que mencioné antes, en la sección de Rendimiento.
>
> - la sección By pair tiene texto en lugar de los iconos. Implementarlos también en los nombres de las columnas. Lo mismo en las secciones Posiciones abiertas, operaciones cerradas
>
> - remover el texto 'Margin granted is what the share took...' de la sección Open positions. Opcionalmente moverlo a un (i). Como aparecen otros textos allí, también mostrarlos en un (i) donde corresponda, a veces se pueden relacionar con una columna de esa tabla, y si no quedan bien ahí, removerlos si no son indispensables.
>
> En ingles, el valor de share en las tarjetas se muestra como '20 %' y en español '20%'. Que en ambos sea '20%'
>
> En el contenido al desplegar 'Conectar una alerta de TradingView', mover el texto 'Use la misma URL y el mismo mensaje...' a un (i) al lado del titulo h2. Lo mismo con el texto de 'Solo se conservan los ultimos cuatro...' al lado de URL del webhook.
>
> Cambiar icono de language por una banderita circular. La americana para EN y la argentina para ES.
>
> Mover el texto 'El freno del servidor está activo: nadie opera...' a un (i) al lado de SIMULACION FORZADA en el header. Mostrarlo solo cuando corresponda.

- [x] L.10 The second round, inline except the tables (a Sonnet writer, for context):
  - Done (`b558c6c`): the drawdown area fades from the waterline to its deepest fall in the loss colour; Delete strategy keeps its words beside its icon (`DANGER_CONTROL`), the one destructive button that does; the Overview's wallet sits left of the balance (`Figure inline`) and a stale balance says so behind an (i) right of it, the eyebrow row alone; a strategy's PnL is the size of the figures beside it; "Deepest drawdown" reads "Drawdown" (ES keeps "Caída máxima"); a range is said in words in tooltips ("PnL, last 30 days"; "1A" was the 1Y range in Spanish); a card's name and its enabled mark share one centred line; a share reads "20%" in both languages (the space was in ES, not EN). 13 of 13 hand mutations killed.
  - Done (`7acc919`): another author's page draws its card's figures in one row at the top of Performance (`CardFigureGrid`, shared with the cards; `RecordFigures`), the return and the fall following the chart's range from the record, one read (`RECORD_STALE_MS` 60 s) for the row and the record below; the old figure card and five dead keys go; the webhook's two hints behind (i)s beside its heading and its URL's label; round flags (US for EN, AR for ES, theme tokens `flag-*`) on the language switch; the brake's text moves from Explore to an (i) beside "Simulation forced" (`InfoTip`, opening below), shown only under the brake. 13 of 13 hand mutations killed.
  - Done (`65e0486`, Sonnet writer, reviewed and mutated by the parent): column names as icons with their names in tooltips (`ColumnHead`) in By pair, Open positions and Closed trades; the margin note and the incomplete-fees note become their column's tooltip; the dry-run notes go behind one (i) beside each section's heading. Supersedes decision 46 (notes below the table). The PnL tip reuses `feesIncompleteHint` (no leading asterisk); `feesIncompleteNote` is gone. Each icon header is a tab stop, as every figure icon is. 12 of 12 hand mutations killed (one survivor, the tip's placement, closed by `ColumnHead.test.tsx`); 3787 frontend tests, lint green.
  - Win rate's icon: a trophy (`Trophy`), the owner's choice in the third round (L.11).

### The owner's third round (2026-11-09), verbatim

Sent after reading the second round.

> El selector de idioma muestra la opción a la que cambiar, en lugar de la opción activa. Si tengo seleccionado ES, mostrar ES. Si tengo seleccionado EN, mostrar EN
>
> En overview:
> - aplicar align ítems center al contenedor del saldo PnL return y drawdown, que encabezan el chart.
>
> En las tarjetas de estrategia:
> - en el valor de Subscribers, mostrar solo los que esten en vivo para que sea un solo valor. Aclarar que son en vivo en su tooltip.
> - mover el icono de PnL (el que muestra +x USDT) a la izquierda de Return. Este icono solo se muestra en My strategies, y se podría mostrar también en My subscriptions. Darle el mismo formato que el resto de iconos.
>
> En la vista de una estrategia:
> - aplicar align ítems center al contenedor del h1 y el tag de enabled.
> - mostrar los iconos en una sola fila. Actualmente en desktop se dividen en dos filas.
> - en estrategia ajena, los iconos de Record no se terminaron de unificar con Performance. En My results siguen estando los iconos de PnL Return y Drawdown, de los cuales estos dos ultimos, se repiten en Performance. Que se muestren solo en la sección Performance, y si está seleccionado My results los valores de return y drawdown sean los propios y se agregue el PnL. Mostrarlos en una sola fila. Habiendo simplificado Suscriptores a un solo valor, debería haber más espacio. Si aún asi, no lo hubiera, omitir PnL.
>
> Para el icono de Win rate, vamos con el trophy.

- [x] L.11 The third round, inline:
  - Built, awaiting its commit and the owner's read: the language switch shows the language in use (its flag and code) and its name says what pressing it does (`app.language`); the Overview's balance and the figures beside it share one middle line; a card's subscribers are the live count alone ("Live subscribers" in the tooltip; sorting by subscribers follows it); a PnL is a figure of the card's grid, left of the return (`CardFigureGrid pnl`): the author's on My strategies, the reader's own all-time PnL on My subscriptions ("Your PnL", from their report in the strategy); another author's page centres its name and its mark, and draws its figures in one row wherever its column holds eight (a container query, 32rem; four a row below it); under My results that row carries the reader's own PnL, contribution and drawdown over the chart's range, and the report below draws no ledger line of its own (`StrategyPerformance ledger={false}`); the PnL, a ninth figure, goes where the column holds one row of eight but not of nine (32rem to 40rem, the owner's word); the record is not read until its view is known; win rate's icon is a trophy. Found while rendering: a card's first four columns stayed the phone's explicit `minmax(0, 1fr)` on lg, so a long PnL (+2058.38 USDT) ran into the return; the card's grid drops them on lg (`lg:grid-cols-none`) and no column is narrower than its value (`minmax(max-content, 1fr)`). 31 of 31 hand mutations killed; 3793 frontend tests, lint green.

### The owner's fourth round (2026-11-09), verbatim

Sent after reading the third round.

> Aplicar place ítems center a los iconos de los grid los distribuye mejor cuando un item tiene un valor de varios caracteres. Por ejemplo PnL con '+2058,38 USDT' queda muy cercano a Return y alejado de Closed trades. Con esta solucion los iconos se separan del borde izquierdo, perdiendo un poco la prolijidad de la tarjeta. Cómo se podría conseguir lo mejor de ambos? En la vista de una estrategia ajena, quedaron bien distribuidos. No se si tenga la misma configuración, pero a lo mejor sirve.
>
> En las tarjetas de estrategia:
> - en las tarjetas de My strategies colocar el switch de activar/desactivar a la altura del titulo de la estrategia, en la esquina derecha, asi los iconos tienen más lugar.
> - Como el tag de enabled es muy repetitivo, en las tarjetas, cambiarlo por un circulo relleno de color. Si está activa o deshabilitada, vos decidis qué colores usar, verde, gris, rojo u otros.
>
> En la vista de estrategias:
> - en la vista de una estrategia ajena, el tag de enabled usa un estilo distinto al de una estrategia propia. Que sean consistentes.

- [x] L.12 The fourth round, inline:
  - Built, awaiting the owner's read: a card's figures are spread as another author's page spreads them, the best of both the owner asked for: on lg each column is as wide as its value, the first at the card's left edge and the last at its right, the room left shared out equally between them (`lg:auto-cols-max lg:justify-between`), so a long PnL takes nothing from its neighbours and the left edge stays straight. The price: a middle figure no longer sits under the same figure of the card above, since each card's columns follow its own values. My strategies' switch sits on the title's line at its right end, so the figures have the card's width. A card marks whether its strategy runs with a filled dot (`EnabledDot`): green when it runs, grey when it does not, never the loss colour since a stopped strategy is not a fault; the word is the dot's name and tooltip. A strategy's page, the author's own or another author's, draws one mark beside its name (`EnabledBadge`, the own page's square mono style; Archived on an archived one). 12 of 12 hand mutations killed; 3795 frontend tests, lint green.

### The owner's fifth round (2026-11-09), verbatim

> En las tarjetas de strategies:
> - En My subscriptions y Explore se usa un gap de * 3 pero en My strategies se usa * 6. Que los espaciados sean consistentes entre vistas. Aplica a Overview, Settings, etc. * 3 está bien.

- [x] L.13 One spacing for every view, inline:
  - Built, awaiting the owner's read: every view stacks its blocks 3 apart (`gap-3`), as Explore and My subscriptions did: My strategies' toolbar, sort and cards; the Overview's pools (were 10); Settings' sections and key cards (were 6 and 4); a strategy's page, own and another author's (column, report boxes, positions, trades; were 6 and 8). The one wider step stays the page title's to what follows (6): a stack holding the `h1` keeps `gap-6`, and where the title shares the stack (Settings, both strategy headers) it carries `mb-3`. Users' title step was 5, now 6. Dialogs and a block's own inner rhythm (label over field, 2.5 and 3.5) are left alone. `shared/ui/page-spacing.test.ts` reads every view's source and refuses a wider stacking gap anywhere but a title's, so a new view keeps the rule. 7 of 7 hand mutations killed; 3797 frontend tests, lint green.
  - The owner then asked for 4 in place of 3 (2026-11-09, verbatim: "Mejor pone las que son *3 en * 4 y luego ya si: push y PR"): every stack of blocks is `gap-4` (16 px): card lists, report boxes, sections, item lists, a page's loading and not-found states; inside a block (a card's lines, forms, the aside's controls, sliders) the rhythm stays 3. The title's step stays 6: `mb-2` where it shares the stack. The source scan refuses a stack wider than 4 anywhere but a title's, and a borderless `gap-3` stack in any `*Page.tsx`; the stacks in the report components (PoolPanel, StrategyPerformance, PublicRecordReport, the positions sections) are moved but not scanned. 6 of 6 hand mutations killed; 3798 frontend tests, lint green.
