# Exchange Credentials Specification

> **Revised 2026-09-24 (owner decision 18).** The earlier READ/TRADE split is
> withdrawn. Each exchange holds ONE key in the vault, used for reading and
> trading. There is no `purpose` column, no per-purpose loading, no rewiring of
> read call sites to a separate key, and no rule 8(c). Rule 8(d) (same-account
> check, design OQ4) is moot. A key that cannot trade is accepted with a
> warning, and live opening signals on that exchange are refused up front.
>
> **Revised 2026-09-25 (owner decisions 20, 21, 22, new and binding).** The
> worker no longer refuses to start over a missing key: an exchange with an
> enabled pool and no key is DEGRADED, not a startup failure (decision 20).
> Saving a key also enables that exchange's one futures pool (decision 21). A
> key can be deleted, but only when the exchange is disabled and flat
> (decision 22); the pool is disabled in the same transaction.

## Purpose

Every exchange credential lives envelope-encrypted in the vault, one active key
per exchange, used both for venue reads (balance sync, balance refresh,
venue-position reads, reconciliation scan, booking prepare) and for order
placement. Application settings hold no Bybit or Binance key. A key is
validated when it is saved (a live read must succeed, and withdraw permission
is refused), its permission snapshot and trade capability are recorded at save
time, and it is never returned to a client beyond a last-4 hint and that
snapshot. A new key for an exchange supersedes the previous one.

## Requirements

### Requirement: One Active Credential Per Exchange

The vault MUST store at most one active credential row per exchange. The
system MUST keep enforcing this with the existing partial unique index
`ux_exchange_credentials_one_active_per_exchange` on `(exchange) WHERE
is_active`. No `purpose` attribute exists on a credential.

#### Scenario: A second active row for the same exchange is rejected

- GIVEN Bybit already has an active credential
- WHEN a second row is inserted as active for Bybit without deactivating the first
- THEN the database MUST reject the write via `ux_exchange_credentials_one_active_per_exchange`

#### Scenario: Loading an exchange with no stored key refuses loudly

- GIVEN Binance has no active credential
- WHEN the worker attempts to load the Binance credential
- THEN the load raises `CredentialNotFound` naming the exchange, and no other credential is substituted

### Requirement: Reads and Orders Sign With the Exchange's Vault Key

Every venue read (balance sync, balance refresh, venue-position reads, the
reconciliation scan, booking prepare) and every order MUST sign with the
active vault credential of the pool's exchange. In particular, Binance's read
paths MUST load the vault key instead of the key formerly read from `.env`.

#### Scenario: Binance balance sync uses the vault key

- GIVEN pool `(binance, usdt-m, USDT)` and an active Binance vault credential
- WHEN `balance.sync` runs for that pool
- THEN the request to Binance is signed with the vault credential, and no key is read from application settings

#### Scenario: Bybit reads and orders use the same key

- GIVEN pool `(bybit, usdt-m, USDT)` and an active Bybit vault credential
- WHEN a venue-position read and then a `FuturesMarketOrder` are signed for that pool
- THEN both are signed with that one credential

### Requirement: No Exchange Key Lives in Application Settings

Application settings (`.env` and `Settings`) MUST NOT hold any Bybit or
Binance API key or secret. Every Bybit and Binance credential MUST be read
exclusively from the encrypted vault, including by diagnostic scripts, which
MUST print which key (last 4) they are signing with.

#### Scenario: Settings carry no Bybit or Binance credential fields

- GIVEN the running configuration
- WHEN application settings are inspected
- THEN no field holds a Bybit or Binance API key or secret value

#### Scenario: A stale key left in .env is ignored, not used

- GIVEN `.env` still contains a `BINANCE_API_KEY` line from before this change
- WHEN the worker starts and signs a Binance read
- THEN the value in `.env` is ignored and the read signs with the vault key

### Requirement: Startup Self-Test Per Exchange

> **Revised 2026-09-25 (owner decision 20).** The former "refuse to start when
> an exchange with an enabled pool has no key" rule is withdrawn and replaced
> below: a missing key is a per-exchange DEGRADED state, never a reason to
> refuse startup.

At worker startup, the system MUST attempt to decrypt every active credential
row and MUST refuse to start if any of them fails to decrypt, naming the
exchange. The system MUST NOT refuse to start when an exchange that has an
enabled Bybit or Binance pool has no active credential; instead it MUST log
exactly one ERROR naming that exchange and how to store a key, in both
DRY_RUN and live mode (under DRY_RUN `balance.sync` still reads real
balances), and the worker MUST still begin accepting jobs. The system MUST
NOT attempt any balance or position read for a DEGRADED exchange. Every
exchange other than a DEGRADED one, including its own closing signals, MUST
be unaffected. An empty vault MUST remain acceptable when no Bybit or Binance
pool is enabled.

#### Scenario: A decryption failure still refuses to start

- GIVEN Bybit's active credential row fails to decrypt
- WHEN the worker starts
- THEN startup fails before accepting jobs and the error names `bybit`

#### Scenario: A missing key degrades its own exchange without stopping the worker

- GIVEN pool `(binance, usdt-m, USDT)` is enabled and Binance has no active credential
- WHEN the worker starts
- THEN it logs exactly one ERROR naming `binance` and how to store a key, attempts no balance or position read for Binance, and still begins accepting jobs

#### Scenario: A DEGRADED exchange does not affect any other exchange

- GIVEN Binance is DEGRADED (no active credential) and Bybit has an active, decryptable credential
- WHEN the worker starts and later processes a Bybit signal, including a closing one
- THEN Bybit is unaffected: its reads and orders proceed exactly as if Binance were fully configured

#### Scenario: Startup passes when every required key decrypts

- GIVEN every exchange with an enabled pool has an active, decryptable credential
- WHEN the worker starts
- THEN the self-test passes and the worker begins accepting jobs

### Requirement: Live-Read Validation On Save

Saving a new or rotated credential MUST perform a live read against the venue
using that credential before the row is committed as active. A failed live
read MUST refuse the save and MUST store nothing. A venue that cannot be
reached MUST be reported distinctly from a venue that rejects the key.

#### Scenario: A working key passes the live-read check

- GIVEN a Bybit API key and secret the venue accepts
- WHEN it is saved for Bybit
- THEN a live read succeeds and the row is stored as active

#### Scenario: A key that cannot authenticate is refused

- GIVEN an API key/secret pair the venue rejects
- WHEN it is submitted for save
- THEN the live read fails, the save is refused with a stated reason, and nothing is stored

### Requirement: Withdraw Permission Refuses The Save

A credential whose permission snapshot includes withdrawal authority MUST be
refused at save time. An internal-transfer permission (for example Bybit's
`AccountTransfer`) MUST NOT be treated as withdrawal authority and MUST be
allowed.

#### Scenario: A key with withdraw permission is refused

- GIVEN a Binance key with `enableWithdrawals=true`
- WHEN it is submitted for save
- THEN the save is refused with a stated reason and nothing is stored

#### Scenario: Internal transfer alone is allowed

- GIVEN a Bybit key whose permissions include only `AccountTransfer` (no withdrawal authority)
- WHEN it is submitted for save
- THEN the save is not refused on withdrawal grounds

### Requirement: A Key Without Trade Capability Is Accepted With a Warning

A credential that passes the live read and carries no withdraw permission MUST
be accepted even when its permission snapshot shows it cannot trade futures.
The save MUST record the key's trade capability, MUST return a read-only
warning to the caller, and the panel MUST mark that exchange as read-only.

#### Scenario: A read-only key is stored and flagged

- GIVEN a Binance key the venue accepts, without withdraw permission, with `enableFutures=false`
- WHEN it is saved for Binance
- THEN the row is stored as active with trade capability false, and the response carries a read-only warning

#### Scenario: A trading key is stored without a warning

- GIVEN a Bybit key the venue accepts, without withdraw permission, whose permissions allow futures trading
- WHEN it is saved for Bybit
- THEN the row is stored as active with trade capability true, and no read-only warning is returned

#### Scenario: Keys sealed before this change count as trade-capable

- GIVEN an active row sealed before the permission snapshot existed, by a store script that refused keys unable to trade
- WHEN its trade capability is read
- THEN it is trade-capable, and its permission snapshot is shown as not validated

### Requirement: Live Opening Signals On a Read-Only or Keyless Exchange Are Refused Up Front

> **Revised 2026-09-25 (owner decision 20).** With the startup refusal gone,
> this requirement is the SOLE mechanism that refuses a live open on a
> keyless exchange, not a defensive backstop.

With `DRY_RUN=false`, an opening signal whose pool's exchange has an active
credential without trade capability, or has no active credential, MUST be
refused before the pool's advisory lock is acquired, MUST NOT create a
reservation, and MUST log exactly one WARNING naming the exchange and telling
the owner to store a key that can trade. Closing signals MUST NOT be refused by
this rule. Under `DRY_RUN=true` this rule MUST NOT refuse anything, because no
order reaches a venue.

Trade capability is read from the value recorded at save time, never from a
live venue query at signal time.

#### Scenario: A live opening signal on a read-only exchange is refused

- GIVEN `DRY_RUN=false`, pool `(binance, usdt-m, USDT)`, and an active Binance credential without trade capability
- WHEN an opening signal for a strategy bound to that pool is processed
- THEN it is refused before the pool's advisory lock is acquired, no reservation is created, and exactly one WARNING names `binance`

#### Scenario: A closing signal on a read-only exchange is not refused by this rule

- GIVEN `DRY_RUN=false`, pool `(binance, usdt-m, USDT)`, an active Binance credential without trade capability, and an open position
- WHEN a closing signal for that position is processed
- THEN this rule does not refuse it, and the close proceeds to the venue as today

#### Scenario: Under DRY_RUN a read-only key refuses nothing

- GIVEN `DRY_RUN=true` and an active Binance credential without trade capability
- WHEN an opening signal for a Binance pool is processed
- THEN this rule does not refuse it

#### Scenario: A live opening signal on a keyless (DEGRADED) exchange is refused

> **Added 2026-09-25 (owner decision 20).**

- GIVEN `DRY_RUN=false`, pool `(binance, usdt-m, USDT)` is enabled, and Binance has no active credential
- WHEN an opening signal for a strategy bound to that pool is processed
- THEN it is refused before the pool's advisory lock is acquired, no reservation is created, and exactly one WARNING names `binance`

#### Scenario: A key deleted just before this check refuses the very next opening signal

> **Added 2026-09-25 (owner decision 22).**

- GIVEN Binance had an active, trade-capable credential, and it is then deleted (see Requirement: Deleting a Credential Requires the Exchange To Be Flat)
- WHEN the next opening signal for a strategy bound to Binance's pool is processed
- THEN it is refused by this rule, with no lock and no cache involved in observing the deletion

### Requirement: Rotation Supersedes The Previous Active Row

Storing a new credential for an exchange that already has an active row MUST
deactivate the previous row in the same transaction that activates the new
one, so exactly one row remains active for that exchange afterward. The
previous row MUST be retained, deactivated, not deleted. Two concurrent saves
for one exchange MUST NOT both succeed.

#### Scenario: Rotating a key deactivates the old row

- GIVEN Bybit has an active row `A`
- WHEN a validated new key is saved for Bybit
- THEN the new row becomes active, row `A` becomes inactive, and `A` still exists in storage

#### Scenario: A concurrent save is refused, not merged

- GIVEN two validated keys are saved for Bybit at the same instant
- WHEN both transactions commit
- THEN exactly one succeeds and the other is refused as a concurrent save, naming no secret

### Requirement: Credential Data Never Returned Beyond Last-4 and Permissions

No API surface MUST return a decrypted key or secret to a client. Reading a
credential's state MUST expose only the last four characters, the trade
capability, and the permission snapshot recorded at save time.

#### Scenario: Listing credentials exposes no secret

- GIVEN active credentials exist for Bybit and Binance
- WHEN the credential list is read
- THEN each entry shows only its last four characters, its trade capability and its stored permission snapshot, and no full key or secret value

#### Scenario: Permissions shown are the snapshot, not a live requery

- GIVEN a credential was saved with a recorded permission snapshot
- WHEN its permissions are displayed later
- THEN the displayed permissions are the stored snapshot from save time, not a fresh live query

### Requirement: Saving A Credential Enables The Exchange's Futures Pool

> **Added 2026-09-25 (owner decision 21).**

Saving a credential for an exchange MUST also enable that exchange's one
configured futures pool, in the same transaction as the credential write.
Which pool an exchange enables MUST come from a fixed, code-defined mapping
(exchange to venue and settlement currency), never from the request. The
system MUST NOT expose any endpoint or view that lets the owner enable,
disable or otherwise manage a pool directly.

#### Scenario: The first key saved for an exchange enables its pool

- GIVEN Binance has no active credential and its futures pool is disabled
- WHEN a valid, trade-capable Binance key is saved
- THEN Binance's futures pool becomes enabled in the same transaction as the credential write

#### Scenario: Re-saving a key for an already-enabled pool changes nothing about the pool

- GIVEN Bybit's futures pool is already enabled
- WHEN a new Bybit key is saved (rotation)
- THEN Bybit's futures pool remains enabled with its previously configured minimum order size unchanged

#### Scenario: No pool-management surface exists

- GIVEN the admin API and the panel
- WHEN they are inspected for a way to enable, disable, or otherwise configure a pool directly
- THEN no such endpoint or view exists; a pool's enabled state changes only as a side effect of saving or deleting a credential

### Requirement: Deleting a Credential Requires the Exchange To Be Flat

> **Added 2026-09-25 (owner decision 22).**

Deleting an exchange's active credential MUST be refused, naming what is
unmet, unless every strategy bound to that exchange's pool is disabled AND
the pool holds no open exposure (no allocation with non-zero net base, no
live reservation, no in-flight execution attempt). The exposure check and
the credential deactivation MUST be serialized against a concurrent
allocation or archive on the same pool by the pool's own advisory lock, the
same one `AllocateCapital` and archive already use. On success, the
credential row MUST be deactivated (retained, never physically deleted) and
the exchange's pool MUST be disabled, in the same transaction. Replacing a
credential (rotation) MUST NOT be subject to this precondition.

#### Scenario: Deletion is refused while a strategy on the exchange is enabled

- GIVEN Bybit has an active credential and an enabled strategy bound to Bybit's pool
- WHEN deletion of the Bybit credential is requested
- THEN it is refused, naming the enabled strategy, and the credential remains active

#### Scenario: Deletion is refused while the exchange holds an open position

- GIVEN Bybit has an active credential, every strategy bound to Bybit's pool is disabled, and one holds a non-zero net position
- WHEN deletion of the Bybit credential is requested
- THEN it is refused, naming the open position, and the credential remains active

#### Scenario: Deletion succeeds when the exchange is flat

- GIVEN Bybit has an active credential, every strategy bound to Bybit's pool is disabled, and none holds an open position or a live reservation
- WHEN deletion of the Bybit credential is requested
- THEN the credential row is deactivated and retained, Bybit's pool is disabled in the same transaction, and Bybit is afterward reported with no active credential

#### Scenario: A concurrent allocation and a deletion on the same pool are serialized

- GIVEN an allocation for a strategy on Bybit's pool is in flight
- WHEN a deletion of Bybit's credential is requested at the same time
- THEN the two are serialized by the pool's advisory lock: whichever commits its reservation first is the one the other's exposure check or refusal observes; no reservation is silently missed by the exposure check

#### Scenario: Replacing a credential is never refused by this precondition

- GIVEN Bybit has an enabled strategy and an open position
- WHEN a new, validated Bybit key is saved to replace the active one (rotation, not deletion)
- THEN it succeeds exactly as any other rotation, unaffected by this requirement
