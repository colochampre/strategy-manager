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

> **Revised 2026-09-29 (owner decisions 24 and 30, design addendum "key policy
> after probe P6").** Neither venue lets this system read everything it needs
> about a key. The record therefore says how each fact was established
> (`VERIFIED` by the venue, `OWNER_CONFIRMED` by the owner, or `UNRECORDED` for
> a row sealed before this change) and never claims more than was. The earlier
> "permission snapshot" is withdrawn: no raw permission payload is stored or
> shown, because it carries whitelisted IPs, the user id and the KYC region.
> Only derived facts are kept. Binance's `canTrade` and `canWithdraw` are never
> read for any purpose: they are account-level, and both were true on a key that
> could neither trade futures nor withdraw.

## Purpose

Every exchange credential lives envelope-encrypted in the vault, one active key
per exchange, used both for venue reads (balance sync, balance refresh,
venue-position reads, reconciliation scan, booking prepare) and for order
placement. Application settings hold no Bybit or Binance key. A key is
validated when it is saved (a live read must succeed, and a key that can
withdraw is refused wherever the venue lets the system see that), the facts
about it are recorded at save time together with how each was established, and
it is never returned to a client beyond a last-4 hint and those facts. A new
key for an exchange supersedes the previous one.

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

### Requirement: A Key That Can Withdraw Refuses The Save

> **Revised 2026-09-29 (owner decisions 24 and 30).**

How "this key cannot withdraw" is established depends on what the venue lets
the system see, and the saved record MUST say which it was.

For Bybit it is VERIFIED, server-side and fail-closed: `permissions.Wallet`
from the key-info read MUST be a list whose tokens all belong to the
internal-transfer allowlist (`AccountTransfer`, `SubMemberTransfer`). Any other
token, or a `Wallet` that is missing or not a list, MUST refuse the save. An
internal-transfer permission MUST NOT be treated as withdrawal authority.

For Binance nothing reachable reveals it, so it is OWNER_CONFIRMED: the save
MUST be refused unless the owner has confirmed that withdrawals are disabled,
and the confirmation MUST be recorded with the time it was given (the server
clock, never a client value). That check MUST run before any venue call, so
nothing is sent to the venue for a key that cannot be stored.

A confirmation belongs to the key it was given for. A rotation stores the new
key with its own confirmations and MUST NOT inherit any from the previous one.

#### Scenario: A Bybit key with withdraw permission is refused

- GIVEN a Bybit key whose `permissions.Wallet` includes `Withdraw`
- WHEN it is submitted for save
- THEN the save is refused naming the offending permission tokens, not the payload, and nothing is stored

#### Scenario: A Bybit permission outside the internal-transfer allowlist is refused

- GIVEN a Bybit key whose `permissions.Wallet` includes a token that is neither `AccountTransfer` nor `SubMemberTransfer`
- WHEN it is submitted for save
- THEN the save is refused (fail-closed) naming that token, and nothing is stored

#### Scenario: A Bybit answer without a usable Wallet list is refused

- GIVEN Bybit's key-info answer has no `Wallet` entry, or `Wallet` is not a list
- WHEN the key is submitted for save
- THEN the save is refused as permissions unavailable, nothing is stored, and exactly one WARNING names the exchange and carries no payload

#### Scenario: Internal transfer alone is allowed

- GIVEN a Bybit key whose `permissions.Wallet` holds only `AccountTransfer`
- WHEN it is submitted for save
- THEN the save is not refused on withdrawal grounds, and the withdraw check is recorded as VERIFIED

#### Scenario: A Binance key without both confirmations is refused before the venue is called

- GIVEN a Binance key, and the owner has confirmed neither, or only one, of "withdrawals disabled" and "Enable Futures"
- WHEN it is submitted for save
- THEN the save is refused naming exactly which confirmation is missing, no request is sent to Binance, and nothing is stored

#### Scenario: A Binance key with both confirmations records them, never a verification

- GIVEN a Binance key the venue accepts, and the owner has confirmed both "withdrawals disabled" and "Enable Futures"
- WHEN it is saved for Binance
- THEN the row is stored as active with its withdraw check OWNER_CONFIRMED and the confirmation time from the server clock, and it is never recorded as VERIFIED

#### Scenario: A confirmation on a Bybit key is refused, not ignored

- GIVEN a Bybit key submitted with a true owner confirmation
- WHEN it is submitted for save
- THEN the save is refused as not applicable, naming the confirmation field, and nothing is stored

#### Scenario: A rotation inherits no confirmation

- GIVEN Binance has an active row carrying owner confirmations
- WHEN a new Binance key is saved with its own confirmations
- THEN the new row carries the confirmations given with it and the previous row's confirmations stay on the previous row

### Requirement: A Key Without Trade Capability Is Accepted With a Warning

> **Revised 2026-09-29 (owner decisions 24 and 30).**

A credential that passes the live read and is not refused on withdrawal grounds
MUST be accepted even when it cannot trade futures, wherever the venue lets the
system see that. The save MUST record the key's trade capability and how it was
established, MUST return a read-only warning to the caller when the capability
is false, and the panel MUST mark that exchange as read-only.

For Bybit trade capability is VERIFIED from `readOnly` on the key-info read (0
can trade, 1 is read-only). The permission lists MUST NOT be used for it: a
read-only key still lists `ContractTrade` and `Derivatives`. A missing
`readOnly` MUST refuse the save as permissions unavailable.

For Binance a key without "Enable Futures" still reads every futures endpoint,
so the live read proves nothing about trading. Trade capability is
OWNER_CONFIRMED: the owner confirms "Enable Futures" and the confirmation is
recorded with the time it was given. A confirmation states a capability, never
an incapability. "Not verified" is state carried by the record, not a warning.
A wrong confirmation is caught by the venue: the first live order is rejected
and alerts the owner.

#### Scenario: A read-only Bybit key is stored and flagged

- GIVEN a Bybit key the venue accepts, without withdraw permission, whose key-info answer has `readOnly=1` and still lists `ContractTrade`
- WHEN it is saved for Bybit
- THEN the row is stored as active with trade capability false, VERIFIED, and the response carries a read-only warning

#### Scenario: A trading Bybit key is stored without a warning

- GIVEN a Bybit key the venue accepts, without withdraw permission, whose key-info answer has `readOnly=0`
- WHEN it is saved for Bybit
- THEN the row is stored as active with trade capability true, VERIFIED, and no read-only warning is returned

#### Scenario: A confirmed Binance key is trade-capable without a warning

- GIVEN a Binance key the venue accepts, and the owner has confirmed "Enable Futures" and "withdrawals disabled"
- WHEN it is saved for Binance
- THEN the row is stored as active with trade capability true, OWNER_CONFIRMED with its confirmation time, and no read-only warning is returned

#### Scenario: Keys sealed before this change count as trade-capable and unrecorded

- GIVEN an active row sealed before facts were recorded, by a store script that refused keys unable to trade
- WHEN its trade capability is read
- THEN it is trade-capable, both its trade capability and its withdraw check are UNRECORDED, it has no validation time, and it is shown as not validated

### Requirement: Each Recorded Fact Names Who Established It

> **Added 2026-09-29 (owner decisions 24 and 30).**

A credential row MUST record, for trade capability and for the withdraw check
separately, whether the fact was `VERIFIED` (the venue said so), `OWNER_CONFIRMED`
(the owner said so) or `UNRECORDED` (no record exists). The database and the
domain MUST refuse the same impossible states:

- a confirmation without its time, or a time without a confirmation;
- an owner confirmation of an incapability;
- a row that is half recorded and half legacy;
- a Binance row claiming a verification the venue does not allow;
- a Bybit row carrying an owner confirmation.

The migration that introduces the record MUST NOT write `VERIFIED` or
`OWNER_CONFIRMED` for an existing row, and MUST refuse to downgrade while any
row carries a recorded fact, naming the counts.

#### Scenario: A confirmation and its time exist together or not at all

- GIVEN a row whose trade capability is OWNER_CONFIRMED
- WHEN it is inserted without a confirmation time, or with a time while not OWNER_CONFIRMED
- THEN the database refuses the row

#### Scenario: A Binance row cannot claim a verification

- GIVEN a Binance row whose trade capability or withdraw check is VERIFIED
- WHEN it is inserted
- THEN the database refuses the row

#### Scenario: A Bybit row cannot carry an owner confirmation

- GIVEN a Bybit row whose trade capability or withdraw check is OWNER_CONFIRMED
- WHEN it is inserted
- THEN the database refuses the row

#### Scenario: The migration backfills honestly and its downgrade refuses to erase a record

- GIVEN credential rows sealed before the migration
- WHEN the migration runs
- THEN each row is trade-capable with both facts UNRECORDED and no timestamps, and a downgrade is refused once any row is not in that shape, naming the count of each

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

### Requirement: Credential Data Never Returned Beyond Last-4 and Recorded Facts

No API surface MUST return a decrypted key or secret to a client. Reading a
credential's state MUST expose only the last four characters, the trade
capability with its source and confirmation time, the withdraw check with its
source and confirmation time, the time the save-time live read passed, and
whether internal transfer is permitted (unknown when it was not established).
No raw permission payload MUST be stored or returned.

#### Scenario: Listing credentials exposes no secret

- GIVEN active credentials exist for Bybit and Binance
- WHEN the credential list is read
- THEN each entry shows only its last four characters and its recorded facts, and no full key or secret value

#### Scenario: Facts shown are the recorded ones, not a live requery

- GIVEN a credential was saved with recorded facts
- WHEN they are displayed later
- THEN the displayed facts are the stored ones from save time, not a fresh live query

#### Scenario: No view carries a raw permission payload

- GIVEN a credential saved from a venue answer that carried whitelisted IPs and a user id
- WHEN its state is read through any API surface
- THEN none of those values appear in the response

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
