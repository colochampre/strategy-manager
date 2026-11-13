# Account deletion — tasks

Branch: `feat/account-deletion`, cut from an up-to-date `main` when the owner
says to build. Strict TDD; gate after every unit. Not started.

**Waits for `subscriber-safety`.** The owner pointed out that S2, as written,
blocks an author with subscribers indefinitely, because subscribers do not
leave by themselves and `Leave` does not close a position. S2 is revised once
subscribers can no longer be stranded: refuse only while a subscriber holds a
position, and archive each authored strategy (disable it and end its
subscriptions, as `ArchiveStrategy` does).

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
  - real exposure, listing the symbols;
  - the user's own live subscriptions;
  - their strategies that have live subscribers.

  The dialog lists them, as `DeleteKeyDialog` lists a key's open positions.
- **S3 Effects.** The wipe, close, keep and mark list in `proposal.md`, applied
  in one transaction.
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

- [ ] T1 S2-S5 backend:
  - a migration adding `users.deleted_at`;
  - a `DeleteAccount` use case under `identity/` with ports for exposure,
    subscriptions, authored strategies, credentials and pools;
  - `DELETE /api/me`, covered by the route guard and cross-user sweep tests.

  Route: inline, followed by an independent verifier.
- [ ] T2 S6 admin list and count. Route: inline.
- [ ] T3 S1, S5 frontend: the section, the dialog and the deleted screen, EN
  and ES. Route: inline.
- [ ] T4 S7 policy and terms text. Route: inline.
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
