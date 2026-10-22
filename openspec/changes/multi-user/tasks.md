# Tasks: Multi-user

Sequential PRs A-G (`design.md`, "Delivery"), each cut from `main`. Every PR ships while Cloudflare Access admits only the owner, so production stays single-user in fact until G. Strict TDD and the gate after every unit:
- backend: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`;
- frontend: `npm run lint` and `npm test`.

## Production now

- 2026-10-22: main `a1295e0`, panel bundle `a1295e08340b`, alembic `0029`.
- `DRY_RUN=false`.
- Access admits only the owner. The API verifies the Access assertion itself; `ADMIN_API_TOKEN` is gone from `.env`.
- `users` holds one row, the owner's, created by their first `/api/me`.

## Delivery log

| PR | What | Merge | Deploy |
| --- | --- | --- | --- |
| #84 | Multi-user decisions 1-15, proposal and design; operator-panel PR 25's delivery record | `7a006fc` (parents `2e137f1`, `c4513d1`) | 2026-10-21, pull only (docs) |
| #85 | PR A: identity from Cloudflare Access, `/api/me`, the panel without the token, migration 0029 | `a1295e0` (parents `7a006fc`, `7f878ca`) | 2026-10-22, see "PR A's delivery" |

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
- [ ] B.3 Scoped persistence (AD8): every repository and adapter that reads or writes owned rows takes `user_id` and filters on it. That covers the accounts, allocation, execution, ledger, reconciliation, performance and strategies adapters in the map of 2026-10-21. No unscoped read remains outside an admin use case or the worker's per-user loop. Each scoped method gets one test where a second user's row is present and not returned.
- [ ] B.4 The advisory lock identifies one user's pool. Two users with the same `(exchange, venue, settlement_currency)` never share a lock: proven with the lock-hold harness (`not task.done()` for the same user, done for the other). `assert_pool_lock_keys_distinct` covers every user's pools, or becomes unnecessary if the key is the pool's id. The lock order stays pool lock first, then row locks.
- [ ] B.5 Signal processing: a signal is allocated and executed in its strategy author's pool, with the author's key. Its reservation, execution attempt and ledger rows carry the author's `user_id`. The holding guard reads that user's holdings.
- [ ] B.6 Routers (decision 16):
  - credentials, pools, performance and open positions depend on `current_user` and pass its id down;
  - the other routers keep `require_admin`, and strategies stamp `author_id` from the admin's `User`.
  - `test_every_api_route_is_guarded.py` lists the scoped routes explicitly, and every other `/api` route still forbids a non-admin with 403.
  - **Cross-user tests**, one per scoped endpoint: user B asks for user A's resource and receives 404, or an empty list. No row changes, which includes B's DELETE leaving A's key active.
- [ ] B.7 Worker per `(user_id, exchange)` (AD9):
  - `read_key_coverage` returns sets of pairs, in one statement;
  - one `SyncBalances` per pair with an active key;
  - `_degraded` is keyed by the pair, and one user's failure degrades only that user;
  - `exchange_for`, the balance reader and the venue reader load the key of the row's user.
  - The startup refusal on a key that does not open is unchanged.
  - A Telegram alert names the user's id prefix, never an e-mail.
- [ ] B.8 Reconciliation per user's pool (AD10):
  - the venue's net position is read with that user's key;
  - the ledger side is filtered by `user_id`;
  - discrepancies and booking proposals carry it, and the admin's discrepancy view shows the user's e-mail beside each row.
- [ ] B.9 Tests: one fixture creates the owner's `User`, and the suites that insert owned rows directly pass its id (about 100 files).

### Frontend

- [ ] B.10 Discrepancy rows show the user's e-mail (B.8), with EN/ES copy, ES in "usted". Nothing else changes: `SignInGate` still stops a non-admin, because the pages a user can use arrive with PR C and later.

### Owner-run (production)

- [ ] B.11 Before the deploy: a fresh backup, then rehearse 0030 on a throwaway restore.
  - counts per owned table, unchanged;
  - every `user_id` and `author_id` the owner's;
  - the ledger's `xmin` unchanged;
  - the new constraints present;
  - downgrade to `0029`, then upgrade again.
- [ ] B.12 Deploy:
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

- [ ] B.D.1 Gate (backend and frontend), and an independent verifier over the whole PR.
- [ ] B.D.2 Push and open the PR (on the owner's word).
- [ ] B.D.3 Merge (owner), with a merge commit.
- [ ] B.D.4 Deploy (B.11, B.12).
- [ ] B.D.5 Delivery log row and "Production now".

## PR C-G

Planned in `design.md`, "Delivery". Their tasks are written when the previous PR is merged, so each starts from what production actually is.
