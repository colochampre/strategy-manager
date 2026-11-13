# Account deletion

A user deletes their own account from Settings, without writing to anyone.
Ley 25.326 art. 16 gives five business days to honour a deletion request, and
today nothing can carry one out: the privacy policy sends it by e-mail and no
operation exists.

## Owner decisions (2026-11-12)

- Self-service, not by e-mail: "Para la implementacion, prefiero directamente
  que el usuario pueda gestionarlo en su configuracion o en la seccion que
  corresponda, sin tener que responder un pedido por email".
- An author with subscribers is blocked until clear (asked with three options;
  chosen "Block until clear"): deletion is refused while any of their
  strategies has active subscribers or subscribers with open positions, so
  nobody is left holding a position no signal will close.

## Why anonymise, not delete

`users.id` is referenced by eleven tables with plain NO ACTION foreign keys,
`ledger_entries` among them, and the ledger is append-only (rule 6). So the
user row stays and stops identifying anyone: the personal data goes, the
records others depend on stay, tied to an id that names nobody. This is the
usual pattern (GitHub's "ghost" user, Reddit's "[deleted]"). Whether it is
enough under art. 16 is the lawyer's question 3 (`public-site/proposal.md`).

## What deleting does

- **Refused** (409, with the reasons listed, nothing changed) while the user:
  - holds anything real: `SqlAlchemyLiveExposure.symbols(user_id)`
    (`execution/infrastructure/live_exposure.py:55`) is not empty;
  - has a live subscription of their own (ACTIVE or LEAVING): they leave it first;
  - authors a strategy with a live subscriber.
- **Wiped:**
  - `users.email` becomes `deleted-<id>@invalid`, which keeps the NOT NULL,
    unique and normalised constraints and frees the real address;
  - `users.display_name` becomes NULL;
  - every `exchange_credentials` row of the user is deleted, ciphertext
    included. Deactivating is not enough, because `DeleteCredential` keeps the
    encrypted columns.
- **Closed:**
  - every strategy they author becomes PRIVATE (its `share_token` goes) and is
    disabled;
  - its webhook secret is replaced by a random one nobody holds, so the
    author's TradingView alerts are refused;
  - their capital pools are disabled.
- **Kept, without a name:** ledger entries, execution attempts, reservations,
  signal deliveries and discrepancies.
- **Marked:** a new `users.deleted_at`. `/api/admin/users` leaves those rows
  out and reports how many there are.
- **Signing in again** with the same e-mail creates a new, empty user
  (`find_or_create`), unrelated to the old one. The Cloudflare Access seat
  expires by itself after a month without use, so the app needs no Cloudflare
  token.

## Out of scope

- Restoring a deleted account.
- Deleting the rows themselves, or the old e-mail from backups: the policy
  states the backup retention instead.
