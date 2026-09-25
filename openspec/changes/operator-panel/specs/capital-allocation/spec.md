# Delta for Capital Allocation

> **Revised 2026-09-24.** The allowed-pairs refusal applies to OPENING signals
> only (owner decision 15). The pool capital at open is the balance read INSIDE
> the lock (design finding F1). Two requirements are added: the strategy is
> re-checked inside the lock (design decision 8), and live opening signals on an
> exchange whose key cannot trade are refused before the lock (owner decision
> 18; the full rule lives in `exchange-credentials`).
>
> **Revised 2026-09-25 (owner decision 20).** The requirement below is
> retitled and its body widened to name the keyless (`NO_KEY`) case
> explicitly, not only by cross-reference: with the startup refusal
> withdrawn (decision 20), this pre-lock check is the only thing that keeps a
> keyless exchange from reaching the lock at all.

## ADDED Requirements

### Requirement: Allowed-Pairs Refusal Before Pool Lock

Before acquiring pool `(exchange, venue, settlement_currency)`'s advisory
lock, the system MUST refuse an OPENING signal whose symbol, normalized with
`market_key()`, is not on the owning strategy's allowed-pairs list. The
refusal MUST occur before the availability read, decision, and reservation
write described in Serialized Allocation Decision, and MUST NOT create a
reservation against the pool. A closing signal MUST NOT be refused by the
allowed-pairs list.

#### Scenario: An unlisted pair never reaches the pool's lock

- GIVEN strategy S1 bound to pool `(bybit, usdt-m, USDT)` with allowed pairs `{ETHUSDT}`
- WHEN an opening signal for `SOLUSDT` arrives for S1
- THEN the signal is refused before pool `(bybit, usdt-m, USDT)`'s advisory lock is acquired, and no reservation is created against that pool

#### Scenario: A listed pair proceeds to the normal allocation transaction

- GIVEN strategy S1 bound to pool `(bybit, usdt-m, USDT)` with allowed pairs `{ETHUSDT}`
- WHEN an opening signal for `ETHUSDT` arrives for S1
- THEN the signal proceeds to pool `(bybit, usdt-m, USDT)`'s serialized allocation transaction exactly as it does today

#### Scenario: A close on an unlisted pair is not refused

- GIVEN strategy S1 bound to pool `(bybit, usdt-m, USDT)` holds `SOLUSDT`, which is no longer on its allowed pairs
- WHEN a closing signal for `SOLUSDT` arrives for S1
- THEN the allowed-pairs list does not refuse it

### Requirement: Archived-Strategy Refusal Before Pool Lock

Before acquiring pool `(exchange, venue, settlement_currency)`'s advisory
lock, the system MUST refuse a signal whose owning strategy is archived. The
refusal MUST occur before the availability read, decision, and reservation
write described in Serialized Allocation Decision, and MUST NOT create a
reservation against the pool.

#### Scenario: An archived strategy's signal never reaches the pool's lock

- GIVEN strategy S1 bound to pool `(bybit, usdt-m, USDT)` is archived
- WHEN a signal arrives for S1
- THEN the signal is refused before pool `(bybit, usdt-m, USDT)`'s advisory lock is acquired, and no reservation is created against that pool

### Requirement: Read-Only Or Keyless Exchange Refusal Before Pool Lock

With `DRY_RUN=false`, before acquiring pool `(exchange, venue,
settlement_currency)`'s advisory lock, the system MUST refuse an OPENING
signal when that exchange's active credential cannot trade, or no credential
is stored at all, as specified in `exchange-credentials`. The refusal MUST
NOT create a reservation against the pool.

#### Scenario: A live opening signal on a read-only exchange never reaches the lock

- GIVEN `DRY_RUN=false` and the active Binance credential cannot trade
- WHEN an opening signal arrives for a strategy bound to pool `(binance, usdt-m, USDT)`
- THEN the signal is refused before that pool's advisory lock is acquired, and no reservation is created

#### Scenario: A live opening signal on a keyless exchange never reaches the lock

> **Added 2026-09-25 (owner decision 20).**

- GIVEN `DRY_RUN=false`, pool `(binance, usdt-m, USDT)` is enabled, and Binance has no active credential
- WHEN an opening signal arrives for a strategy bound to that pool
- THEN the signal is refused before that pool's advisory lock is acquired, and no reservation is created

### Requirement: Strategy Re-Checked Inside the Pool Lock

After acquiring pool `(exchange, venue, settlement_currency)`'s advisory lock
and before the availability read, `AllocateCapital` MUST re-read the owning
strategy's policy and MUST skip without a reservation when the strategy is no
longer enabled or has been archived. Archiving a strategy MUST take the same
pool lock while it checks for exposure and writes `archived_at`, so an
allocation and an archive of the same strategy are serialized.

#### Scenario: A strategy disabled and archived while a signal waited for the lock

- GIVEN a signal for strategy S1 on pool `(bybit, usdt-m, USDT)` read S1 as enabled before the lock
- WHEN S1 is disabled and archived before that signal acquires the lock
- THEN the in-lock re-read sees S1 disabled or archived, the allocation skips, and no reservation is created

#### Scenario: An allocation that wins the lock blocks the archive

- GIVEN an allocation for strategy S1 on pool `(bybit, usdt-m, USDT)` holds the pool lock and writes a reservation
- WHEN an archive of S1 then acquires the lock
- THEN the archive sees the live reservation and is refused

### Requirement: Pool Capital At Open Is Recorded Inside the Serialized Allocation Transaction

When a reservation is created for pool `(exchange, venue,
settlement_currency)` inside its serialized allocation transaction (per
Serialized Allocation Decision), the system MUST also record that pool's
capital at that moment onto the reservation, reusing the `pool_balance.total`
read `AllocateCapital` performs inside the lock (`allocate_capital.py:131`),
not the pre-lock read used to size the requested amount. This MUST introduce
no additional read and no additional lock.

#### Scenario: A reservation records its pool's in-lock capital in the same transaction

- GIVEN pool `(bybit, usdt-m, USDT)` reads 510 USDT before the lock and 500 USDT inside it when a signal is allocated
- WHEN the reservation is written inside pool `(bybit, usdt-m, USDT)`'s advisory-locked transaction
- THEN the reservation's pool-capital-at-open value is 500 USDT, and no read beyond the transaction's existing in-lock `pool_balance.total` read was performed
