# Account deletion — tasks

Branch: `feat/account-deletion`, cut from `main` at `0419adb` on 2026-11-18.
Strict TDD; gate after every unit. In progress.

**S2 revised (L4-L6, 2026-11-18).** `subscriber-safety` is delivered, so
subscribers can no longer be stranded. Only a position refuses the deletion.
Every other seat ends with it.

**Risk:** item 1 (it irreversibly overwrites and deletes stored personal data
and keys), item 2 (identity and credentials) and item 4 (it must not race an
opening). An independent verifier runs on the backend unit, and the migration
is rehearsed on a throwaway database restored from a fresh backup.

## Specs

- **S1 Settings.** A "Delete account" section at the end of Settings. It says
  what is erased and what is kept. A confirm dialog asks the user to type their
  e-mail. *Assumption: typing the e-mail is the confirmation, as GitHub asks for
  the repository name.*
- **S2 Refusals.** `DELETE /api/me` answers 409 with every reason that applies,
  and changes nothing:
  - real exposure of the user, listing the symbols;
  - a strategy they author on which anyone (a subscriber or the author) holds
    an open position, a live reservation or an in-flight attempt, naming the
    strategy (the exposure `ArchiveStrategy` refuses on).

  The dialog lists them, as `DeleteKeyDialog` lists a key's open positions.
  Live subscriptions are no longer a refusal (L5, L6).
- **S3 Effects.** The wipe, close, keep and mark list in `proposal.md`, applied
  in one transaction. Closing also:
  - disables and archives every strategy the user authors, ending all its
    live subscriptions, the author's own seat included, as `ArchiveStrategy`
    does (L5);
  - ends the user's live subscriptions to other authors' strategies (L6).
- **S4 Concurrency.** The deletion takes every pool advisory lock of the user
  first, then row locks (the project's lock order). It re-checks S2 inside the
  locks. A lock-hold test on real PostgreSQL proves that a concurrent opening
  or subscription waits.
- **S5 After.** The panel shows "Your account was deleted" with a sign-out link
  (Cloudflare Access `/cdn-cgi/access/logout`). Any log line names the user id,
  never the e-mail.
- **S6 Admin.** `/api/admin/users` and `/users` leave deleted users out and show
  "N deleted accounts".
- **S7 Policy and terms.** The privacy policy's `rights.deletion` and the terms'
  `stopping.you` describe the button, what is kept and that backups keep the
  data until they rotate. `PRIVACY_VERSION` is bumped.

## Tasks

- [x] T1 S2-S5 backend. Route: inline, followed by an independent verifier.
  - `4e4fb40`: `DeleteAccount` (`identity/application/delete_account.py`),
    its ports, 12 unit tests against fakes (RED against a stub, then GREEN).
  - `c619bf6`: migration `0045` (`users.deleted_at` and
    `ck_users_deleted_names_nobody`, refusing a deleted row that keeps a real
    e-mail or a name; its 6 tests RED without the CHECK); the adapters
    (`identity/infrastructure/account_deletion.py`); `DELETE /api/me`, 204 or
    409 `ACCOUNT_HOLDS_POSITIONS` (symbols, strategies) or `ACCOUNT_CHANGED`;
    8 route tests on real PostgreSQL (RED on 405 first), including the
    lock-hold test: an opening holding the user's pool lock makes the deletion
    wait, then refuse on the reservation it committed. Removing the pool locks
    turns that test red. The cross-user sweep, the route guard, the
    no-secret sweep and `test_0029_users` know the new route and column.
- [x] T2 S6, in `c619bf6`: `GET /api/admin/users` leaves deleted rows out, and
  `GET /api/admin/users/deleted-count` answers `{"deleted_accounts": N}`, a
  route of its own so the list's body does not change. 3 tests, RED with the
  filter and the route removed.
- [x] T3 S1, S5 frontend, in `c0a016e`. Route: inline.
  - `deleteAccount` and `useDeleteAccount` (`shared/api/me.ts`): every query
    is cancelled before the request; on a 204 the cache is dropped and
    `useAccountDeletedStore` (memory only) tells `App`, which then draws only
    `AccountDeletedScreen`, with no route and no query: a read of
    `GET /api/me` after the deletion would sign the e-mail in again as a new,
    empty account. The screen's link is `/cdn-cgi/access/logout`.
  - `DeleteAccountSection`, last in Settings: what is erased, closed and kept,
    and when it is refused. `DeleteAccountDialog` enables its button only when
    the typed e-mail matches (case and spaces ignored), keeps the focus on
    Cancel, and lists each refusal reason.
  - 13 tests (3 API, 8 section, 2 screen), RED first; the Settings outline
    test gains the section. Frontend 158 files and 3,950 tests, lint clean.
  - Seen in headless Edge at 1400 px on the fixture server, which answers
    `DELETE /api/me` itself (`?fixture=deleteok|deletechanged|deleteerror`,
    refusal by default) so a review never deletes the local account.
- [x] T1.1 S4, the verifier's A1: saving a key and deleting the account at once.
  Route: inline.
  - The deletion holds the user row `FOR UPDATE` and then deletes the keys; a
    save deactivated the old key row first and then needed the user row for
    the new one's FK. Reproduced on real PostgreSQL with the real
    `SaveCredential`, trading and read-only: `DeadlockDetectedError`. The
    other interleaving left an active key on a deleted account.
  - The vault's `store` now takes the owner row `FOR SHARE` before any key
    row and raises `AccountDeleted` once `deleted_at` is set;
    `SaveCredential` answers `ACCOUNT_DELETED` (409). A deadlock that still
    reaches `DELETE /api/me` answers 409 `ACCOUNT_CHANGED`, not a 500.
  - 3 tests, each RED first on an assertion (the deadlock, a save after the
    deletion that stored a key, the route's unhandled 500).
- [ ] T4 S7 policy and terms text. **Blocked:** the privacy policy, the terms
  and `PRIVACY_VERSION` exist only on `feat/public-site`, not merged and on
  standby. The text changes there, with that branch.
- [ ] T5 Migration rehearsal, deploy steps for the owner, and the delivery log.

## Log

- L1 (owner, 2026-11-12): "Cómo se debería gestionar la eliminación de cuenta
  por parte de un usuario? Debería estar disponible? Eso lo remueve de la lista
  de usuarios que admin ve desde /users?"
- L2 (owner, 2026-11-12): "Para la implementacion, prefiero directamente que el
  usuario pueda gestionarlo en su configuracion o en la seccion que corresponda,
  sin tener que responder un pedido por email". Author with subscribers: "Block
  until clear".
- L3 Mapped read-only 2026-11-12. `users` is
  `identity/infrastructure/models.py:19`. Eleven NO ACTION FKs point at
  `users.id`. The latest migration is `0039`.
- L4 (assistant, 2026-11-18): `subscriber-safety` is delivered; proposed
  revising S2 so an author is refused only while a subscriber holds a
  position, each authored strategy is archived, and the user's own live
  subscriptions still refuse.
- L5 (owner, 2026-11-18): "Las primeras dos estan bien. La tercera se refiere
  a la suscripción automática del autor a su propia estrategia? Tengo entendido
  que de esas un autor no puede optar por salir. Que sería que tenga alguna
  viva?" Verified: the author's seat cannot be left (`AuthorCannotLeave`,
  decision 22) and archiving ends it. The third point meant seats on other
  authors' strategies; the assistant proposed ending them at deletion when no
  position is held.
- L6 (owner, 2026-11-18): "Si, me parece bien".
- L7 (assistant, 2026-11-18): L3's "latest migration `0039`" is stale; the
  latest was `0044` and this change adds `0045`.
- L8 Independent verifier on T1/T2, 2026-11-18: no blockers, S2-S6 pass. A1
  (the deadlock above) was change-caused; the owner said "Si, por favor" to
  fixing it (T1.1). Advisories kept:
  - A2: rows that land after the commit, because their FK waited on a row the
    deletion held: a strategy registered, or a seat taken by the user or by
    a third user on an authored strategy. None can open anything (pool
    disabled, strategy archived, secret gone).
  - A3: a SIMULATED position on another author's strategy does not refuse;
    its seat ends and the position stays open. It matches S2 ("real
    exposure"); to confirm with the owner.
  - A4: the lock-hold test's 409 alone would survive removing the pool locks;
    only its advisory-wait check makes that mutation red. No real-PG test
    for a subscription racing the deletion, or for `ACCOUNT_CHANGED`.
  - A5: a repeated DELETE moves `deleted_at`; `users.mode` stays as it was;
    strategy descriptions are kept.
