# Tasks: Multi-user

Sequential PRs A-G (`design.md`, "Delivery"), each cut from `main`. Every PR ships while Cloudflare Access admits only the owner, so production stays single-user in fact until G. Strict TDD and the gate after every unit:
- backend: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`;
- frontend: `npm run lint` and `npm test`.

## Production now

- 2026-10-21: main `7a006fc`, panel bundle `c27540d3f848`.
- `DRY_RUN=false`.
- Access admits only the owner.

## Delivery log

| PR | What | Merge | Deploy |
| --- | --- | --- | --- |
| #84 | Multi-user decisions 1-15, proposal and design; operator-panel PR 25's delivery record | `7a006fc` (parents `2e137f1`, `c4513d1`) | 2026-10-21, pull only (docs) |

## PR A: identity from Cloudflare Access

Design AD1 and AD11 (sign-in only). Every endpoint that exists today stays **admin-only** in this PR, because nothing is scoped by user until PR B. A non-admin who signs in receives 403 everywhere except `GET /api/me`.

**Risk:** item 2 (auth), item 1 (migration 0029) and item 5 (a new dependency). It needs an independent verifier before the PR.

### Backend

- [ ] A.1 Dependency: PyJWT with the `crypto` extra, pinned to an exact release at least two weeks old. `cryptography` is already a dependency.
- [ ] A.2 Domain `identity/domain/user.py`:
  - `User(id, email, created_at, last_seen_at)`;
  - e-mail normalisation, trimmed and lower-cased, with tests.
  - No framework imports.
- [ ] A.3 Migration 0029:
  - creates `users`: `id uuid` pk; `email text` unique, with CHECK `email = lower(email)`; `created_at`; `last_seen_at`;
  - inserts the owner from `ADMIN_EMAIL`, and refuses with a clear message when it is unset;
  - its `downgrade` drops the table.
  - It is rehearsed on a throwaway database restored from a fresh backup (task A.12).
- [ ] A.4 Settings:
  - add `access_team_domain`, `access_aud`, `admin_email` and `dev_user_email`. `model_config` is not touched.
  - The API refuses to start:
    - with neither Access nor a dev e-mail configured;
    - with `dev_user_email` set while `DRY_RUN=false`;
    - with `admin_email` unset.
  - One test per refusal.
- [ ] A.5 Application:
  - the port `IdentityVerifier`;
  - the use case `ResolveUser`, which finds or creates the user by e-mail. Two concurrent first requests create one row: `ON CONFLICT (email) DO NOTHING`, then a read. Proven on real PostgreSQL.
  - `last_seen_at` is written at most once a minute per user.
- [ ] A.6 Infrastructure `AccessJwtVerifier`:
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
- [ ] A.7 FastAPI dependencies:
  - `current_user` reads `Cf-Access-Jwt-Assertion`, or the dev e-mail when configured;
  - `require_admin` builds on it and compares the e-mail with `ADMIN_EMAIL`, case-insensitively.
  - They replace `require_admin_token` on all 9 routers.
  - `strategies/infrastructure/admin_token_invariant.py` and its test are rewritten: every `/api` route depends on `require_admin`, except `/api/me`, which depends on `current_user`. `/webhook/tradingview` and `/health` are unchanged.
- [ ] A.8 `GET /api/me` returns `{email, is_admin, dry_run}`. A non-admin gets 200 here and 403 on every other `/api` route, with one test per router.
- [ ] A.9 Retire the bearer token:
  - first list every caller of the HTTP API outside the panel (scripts, docs);
  - then remove `admin_api_token`, `AdminTokenAuth` and `require_admin_token`.
  - The owner removes `ADMIN_API_TOKEN` from the VPS `.env` after the deploy (A.13). A leftover line is ignored, as with the old key settings.
- [ ] A.10 Tests: one `current_user` override fixture replaces the token header across the existing suites. Each suite keeps one unauthenticated test asserting 401.

### Frontend

- [ ] A.11 The panel without a token:
  - remove `TokenGate`, `token-store` and the `Authorization` header from `shared/api/client.ts`;
  - a 401 reloads the page, so that Access signs the user in again;
  - a 403 shows a "not authorised" state;
  - a `useMe` query feeds the top bar with the e-mail.
  - Update `src/test/harness.tsx` and the tests that set the token.
  - EN/ES copy, with ES in "usted".
  - The fixture config (`vite.fixture.config.ts`, the owner's file) is not committed. If it needs `/api/me`, tell the owner what to add.

### Owner-run (production)

- [ ] A.12 Before the deploy:
  - read the Access team domain and the application's AUD tag in Zero Trust;
  - add `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD` and `ADMIN_EMAIL` to the VPS `.env` with nano;
  - take a fresh backup, and rehearse 0029 on a throwaway restore.
- [ ] A.13 Deploy:
  - pull as `strategy`, `alembic upgrade head`, restart both services;
  - pps.6 for the panel;
  - check: the panel loads with no token prompt, `GET /api/me` shows the owner as admin, and the webhook still answers;
  - then remove `ADMIN_API_TOKEN` from `.env` and restart the API.

### Delivery

- [ ] A.D.1 Gate (backend and frontend), and an independent verifier over the whole PR.
- [ ] A.D.2 Push and open the PR (on the owner's word).
- [ ] A.D.3 Merge (owner), with a merge commit.
- [ ] A.D.4 Deploy (A.12, A.13).
- [ ] A.D.5 Delivery log row and "Production now".

## PR B-G

Planned in `design.md`, "Delivery". Their tasks are written when the previous PR is merged, so each starts from what production actually is.
