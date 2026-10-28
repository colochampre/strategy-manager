# Tasks: Multi-user

Sequential PRs A-G (`design.md`, "Delivery"), each cut from `main`. Every PR ships while Cloudflare Access admits only the owner, so production stays single-user in fact until G. Strict TDD and the gate after every unit:
- backend: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`;
- frontend: `npm run lint` and `npm test`.

## Production now

- 2026-10-27: main `7f67fc3`, panel bundle `5632e763deb5` (#87 changed no frontend), alembic `0030`, certifi `2026.10.23`.
- `DRY_RUN=false`.
- Access admits only the owner. The API verifies the Access assertion itself; `ADMIN_API_TOKEN` is gone from `.env`.
- `users` holds one row, the owner's, created by their first `/api/me`. Every owned row is that user's, and every strategy's `author_id` is theirs.
- The worker reports one enabled pool and one sealed key, Binance's.

## Delivery log

| PR | What | Merge | Deploy |
| --- | --- | --- | --- |
| #84 | Multi-user decisions 1-15, proposal and design; operator-panel PR 25's delivery record | `7a006fc` (parents `2e137f1`, `c4513d1`) | 2026-10-21, pull only (docs) |
| #85 | PR A: identity from Cloudflare Access, `/api/me`, the panel without the token, migration 0029 | `a1295e0` (parents `7a006fc`, `7f878ca`) | 2026-10-22, see "PR A's delivery" |
| #86 | PR B: every owned row belongs to its user, scoped reads, the per-user lock, worker and reconciliation, migration 0030 | `5632e76` (parents `a1295e0`, `814f1eb`) | 2026-10-27, see "PR B's delivery" |
| #87 | Outside this change: certifi 2026.7.22 -> 2026.10.23, which drops the distrusted `emSign ECC Root CA - G3` (eMudhra, Mozilla bug 2083449), and `tests/shared/test_tls_trust.py` to pin it | `7f67fc3` (parents `5632e76`, `39ea058`) | 2026-10-27. Pull as `strategy`; `uv sync --locked` swapped only certifi; both services restarted, both active. The venv's httpx context read `2026.10.23 113 False` (version, distinct root names, G3 present). No WARNING or ERROR in 15 minutes of both journals. No panel step. |

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
- [ ] C.11 Concurrency on real PostgreSQL, with the lock-hold harness:
  - two deliveries of one signal for two users take two different pool locks, and neither waits for the other;
  - two deliveries for one user's pool serialize.

### Frontend

- [ ] C.12 The share editor (`features/strategies/PoolShareEditor.tsx`) edits the signed-in user's subscription (`PATCH /api/subscriptions/{id}`), not the strategy.
  - The strategy page shows that subscription's state, with Subscribe and Leave. LEAVING reads as "closes with the strategy's next close".
  - `NewStrategyDialog` still sends the share, which now becomes the author's subscription.
  - `types.ts` and `strategies.ts` follow the API.
  - EN and ES copy, with ES in "usted".
  - Each changed behaviour gets its test, red first.

### Owner-run (production)

- [x] C.0 The read-only pre-check (2026-10-27). Its results are above, under "Production at planning".
- [ ] C.13 Before the deploy: a fresh backup, then rehearse 0031 and 0032 on a throwaway restore.
  - Counts unchanged on every existing table.
  - 6 subscriptions: 3 ACTIVE at 30 and 3 ENDED at 5.
  - 48 deliveries, with outcomes equal to their signals'.
  - Every reservation and every attempt has its `delivery_id`.
  - The ledger's `(id, xmin)` unchanged.
  - Downgrade to `0030`, then upgrade again.
  - Every query in the script is run on a local throwaway database at `head` before it is handed over.
- [ ] C.14 Deploy:
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

- [ ] C.D.1 Gate (backend and frontend), and an independent verifier over the whole PR.
- [ ] C.D.2 Push and open the PR (on the owner's word).
- [ ] C.D.3 Merge (owner), with a merge commit.
- [ ] C.D.4 Deploy (C.13, C.14).
- [ ] C.D.5 Delivery log row and "Production now".

## PR D-G

Planned in `design.md`, "Delivery". Their tasks are written when the previous PR is merged, so each starts from what production actually is. PR D's 0033 also drops what PR C left unused: `strategies.allocation_percent`. The signals' `status`, `outcome_reason`, `outcome_detail` and `decided_at` stay, because they hold the strategy-level refusals (C.7).
