# Strategy Lifecycle Specification

## Purpose

Governs a strategy's allowed trading pairs, its archival, and the audit trail
of when it was enabled or disabled. A strategy is bound to exactly one
`(exchange, venue, settlement_currency)` capital pool (existing model); this
domain adds the allowlist that scopes which symbols that strategy may trade
within its pool, and the terminal archive state that retires a strategy
without deleting its history.

> **Revised 2026-10-02 (owner decisions 40 and 41).** A pair may be put on the
> list only when the pool's venue lists it. Four requirements are added after
> "New Strategies Require At Least One Allowed Pair". Pairs already stored are
> never revalidated, so the seeding requirement and decision 15 are unchanged.

## Requirements

### Requirement: Allowed-Pairs List Per Strategy

> **Revised 2026-09-24 (owner decision 15).** The list gates OPENING signals
> only. A position already open on a pair that is later removed still closes on
> its signal.

Every strategy MUST have an allowed-pairs list, stored in `market_key()`
canonical form. An OPENING signal for that strategy whose symbol, normalized
with `market_key()`, is not on the list MUST be refused before the strategy's
capital pool's advisory lock is acquired, and MUST NOT create a reservation
against that pool. A CLOSING signal MUST NOT be refused by the list; when its
pair is no longer listed it MUST close anyway and log one WARNING saying so. A
REVERSE on an unlisted pair MUST close the prior position and refuse the
opening half, ending flat.

#### Scenario: Listed pair proceeds

- GIVEN strategy S1 bound to pool `(bybit, usdt-m, USDT)` with allowed pairs `{ETHUSDT}`
- WHEN a signal for `ETHUSDT` arrives for S1
- THEN allocation proceeds normally for pool `(bybit, usdt-m, USDT)`

#### Scenario: Unlisted pair is refused with a WARNING

- GIVEN strategy S1 bound to pool `(bybit, usdt-m, USDT)` with allowed pairs `{ETHUSDT}`
- WHEN an opening signal for `SOLUSDT` arrives for S1
- THEN the signal is refused before the pool's advisory lock is acquired, no reservation is created against pool `(bybit, usdt-m, USDT)`, and exactly one WARNING is logged naming the strategy and the symbol

#### Scenario: A close on a pair removed from the list still closes

- GIVEN strategy S1 holds an open `SOLUSDT` position in pool `(bybit, usdt-m, USDT)` and `SOLUSDT` was then removed from its allowed pairs
- WHEN S1's closing signal for `SOLUSDT` arrives
- THEN the position is closed as it would be for a listed pair, and exactly one WARNING notes that the pair is no longer listed

#### Scenario: A reverse on an unlisted pair ends flat

- GIVEN strategy S1 holds a long `SOLUSDT` position and `SOLUSDT` is no longer on its allowed pairs
- WHEN a signal reversing S1 to short `SOLUSDT` arrives
- THEN the long is closed, the opening half is refused with one WARNING, and no reservation is created for it

#### Scenario: Spelling variants match the same allowed pair

- GIVEN strategy S1 has `ETHUSDT` on its allowed-pairs list
- WHEN a signal arrives spelled `ETHUSDT.P` or `ETHUSDT_PERP`
- THEN the symbol normalizes to the same canonical `market_key` and the signal is treated as listed

### Requirement: New Strategies Require At Least One Allowed Pair

Creating a strategy MUST require at least one allowed pair; a create request
with an empty allowed-pairs list MUST be refused.

#### Scenario: Creating with no pairs is refused

- GIVEN a strategy-creation request with an empty allowed-pairs list
- WHEN the request is submitted
- THEN it is refused and no strategy row is created

#### Scenario: Creating with at least one pair succeeds

- GIVEN a strategy-creation request with allowed pairs `{ETHUSDT}`
- WHEN the request is submitted
- THEN the strategy is created with that allowed-pairs list

### Requirement: The Pairs Available To A Pool Come From Its Venue's Catalogue

> **Added 2026-10-02 (owner decisions 40 and 41).**

The pairs available to a capital pool `(exchange, venue, settlement_currency)`
MUST be exactly the contracts its venue's public catalogue lists that are
perpetual, in trading status, and settled in that pool's settlement currency,
each expressed in `market_key()` form. A dated future, a contract of any other
type, a contract that is not trading, and a contract settled in any other
currency MUST NOT be available. Availability MUST be decided from the
contract's type, status and settlement currency as the venue reports them, and
MUST NOT be decided from the symbol's text alone. One pool's available pairs
MUST NOT be answered from another pool's.

The catalogue MUST be read without any API credential or request signature,
in both `DRY_RUN` modes. Reading it MUST NOT place an order.

#### Scenario: A perpetual settled in the pool's currency is available

- GIVEN pool `(bybit, usdt-m, USDT)` and a venue catalogue listing `STXUSDT` as a trading perpetual settled in `USDT`
- WHEN the pairs available to pool `(bybit, usdt-m, USDT)` are read
- THEN `STXUSDT` is among them

#### Scenario: A dated future is not available

- GIVEN pool `(bybit, usdt-m, USDT)` and a venue catalogue listing `BTCUSDT-25DEC26` as a trading dated future settled in `USDT`
- WHEN the pairs available to pool `(bybit, usdt-m, USDT)` are read
- THEN `BTCUSDT-25DEC26` is not among them

#### Scenario: A perpetual settled in another currency is not available

- GIVEN pool `(binance, usdt-m, USDT)` and a venue catalogue listing `BTCUSDC` as a trading perpetual settled in `USDC`
- WHEN the pairs available to pool `(binance, usdt-m, USDT)` are read
- THEN `BTCUSDC` is not among them

#### Scenario: A contract type other than perpetual is not available

- GIVEN pool `(binance, usdt-m, USDT)` and a venue catalogue listing `AAPLUSDT` with contract type `TRADIFI_PERPETUAL`, trading, settled in `USDT`
- WHEN the pairs available to pool `(binance, usdt-m, USDT)` are read
- THEN `AAPLUSDT` is not among them

#### Scenario: A listing longer than one page is read whole

- GIVEN pool `(bybit, usdt-m, USDT)` and a venue catalogue that answers in two pages, with `STXUSDT` on the second
- WHEN the pairs available to pool `(bybit, usdt-m, USDT)` are read
- THEN `STXUSDT` is among them

#### Scenario: One malformed entry does not hide the rest

- GIVEN pool `(bybit, usdt-m, USDT)` and a venue catalogue in which one entry cannot be parsed and `STXUSDT` is a valid trading perpetual settled in `USDT`
- WHEN the pairs available to pool `(bybit, usdt-m, USDT)` are read
- THEN `STXUSDT` is among them, the malformed entry is not, and exactly one WARNING names how many entries were skipped

### Requirement: A New Strategy's Pairs Must All Be Available To Its Pool

> **Added 2026-10-02 (owner decisions 40 and 41).**

Creating a strategy MUST be refused when any submitted pair, normalized with
`market_key()`, is not among the pairs available to the strategy's capital pool
`(exchange, venue, settlement_currency)`. The refusal MUST name every such
pair, MUST create no strategy row, and MUST log one WARNING. A pair that is
available MUST be accepted in any spelling that normalizes to it.

#### Scenario: An unlisted symbol refuses the registration

- GIVEN pool `(bybit, usdt-m, USDT)` whose available pairs include `ETHUSDT` and do not include `YPF`
- WHEN a strategy is created on pool `(bybit, usdt-m, USDT)` with allowed pairs `{ETHUSDT, YPF}`
- THEN the creation is refused naming `YPF`, no strategy row is created, and one WARNING is logged

#### Scenario: A listed symbol in another spelling is accepted

- GIVEN pool `(bybit, usdt-m, USDT)` whose available pairs include `STXUSDT`
- WHEN a strategy is created on pool `(bybit, usdt-m, USDT)` with allowed pairs `{STXUSDT.P}`
- THEN the strategy is created with allowed pairs `{STXUSDT}`

### Requirement: Replacing Allowed Pairs Validates Only The Pairs Being Added

> **Added 2026-10-02 (owner decisions 40 and 41; decision 15 for the
> exemption).**

Replacing a strategy's allowed-pairs list MUST validate only the pairs that are
not already on the stored list. Each such pair MUST be among the pairs
available to the strategy's capital pool `(exchange, venue,
settlement_currency)`, or the replacement MUST be refused naming every pair
that is not, leaving the stored list unchanged. A pair already on the stored
list MUST be accepted without being looked up, whether the venue still lists
it or not, so that it can be kept or removed. A replacement that adds no pair
MUST NOT depend on the venue's catalogue being readable.

The venue's catalogue MUST NOT be read while the strategy's row is locked. If
the stored list changes between the validation and the write so that a pair
which was not validated would become an addition, the replacement MUST be
refused and MUST leave the stored list unchanged.

#### Scenario: Adding an unlisted symbol refuses the replacement

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` with allowed pairs `{ETHUSDT}`, and that pool's available pairs do not include `BTC`
- WHEN S1's list is replaced with `{ETHUSDT, BTC}`
- THEN the replacement is refused naming `BTC`, and S1's allowed pairs remain `{ETHUSDT}`

#### Scenario: Adding a listed symbol in another spelling is accepted

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` with allowed pairs `{ETHUSDT}`, and that pool's available pairs include `STXUSDT`
- WHEN S1's list is replaced with `{ETHUSDT, STXUSDT_PERP}`
- THEN S1's allowed pairs become `{ETHUSDT, STXUSDT}`

#### Scenario: A delisted pair already stored can be kept

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` with allowed pairs `{ETHUSDT, SFPUSDT}`, and that pool's available pairs no longer include `SFPUSDT`
- WHEN S1's list is replaced with `{ETHUSDT, SFPUSDT, STXUSDT}` and `STXUSDT` is available
- THEN S1's allowed pairs become `{ETHUSDT, SFPUSDT, STXUSDT}`

#### Scenario: A delisted pair already stored can be removed while the venue is unreachable

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` with allowed pairs `{ETHUSDT, SFPUSDT}`, and the venue's catalogue cannot be read
- WHEN S1's list is replaced with `{ETHUSDT}`
- THEN S1's allowed pairs become `{ETHUSDT}` and the catalogue is not read

#### Scenario: A removed delisted pair cannot be added back

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` with allowed pairs `{ETHUSDT}`, after `SFPUSDT` was removed, and that pool's available pairs do not include `SFPUSDT`
- WHEN S1's list is replaced with `{ETHUSDT, SFPUSDT}`
- THEN the replacement is refused naming `SFPUSDT`

#### Scenario: The catalogue is read before the strategy row is locked

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` and a replacement that adds a pair, whose catalogue read has not yet answered
- WHEN another transaction locks S1's row
- THEN that transaction obtains the lock without waiting

#### Scenario: A concurrent edit that would store an unvalidated pair is refused

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` with allowed pairs `{ETHUSDT, SFPUSDT}`, and a replacement with `{ETHUSDT, SFPUSDT, STXUSDT}` that has validated `STXUSDT` only
- WHEN another request removes `SFPUSDT` from S1 before the replacement writes
- THEN the replacement is refused, and S1's allowed pairs are what the other request stored

### Requirement: An Unreadable Catalogue Refuses The Save

> **Added 2026-10-02 (owner decision 41).** The last paragraph and its
> scenario (a pool with no catalogue source) state the designed answer; they
> await the owner's confirmation of open question Q1 in design.md, addendum
> "allowed pairs validated against the venue catalogue", § L.

When a save needs the pairs available to a capital pool `(exchange, venue,
settlement_currency)` and that pool's venue catalogue cannot be read (the venue
is unreachable, answers an error, or returns a listing from which no available
pair can be derived), the save MUST be refused with an error distinct from an
unknown-pair refusal, MUST store nothing, and MUST log the failure. A catalogue
read that failed MUST NOT be remembered as an answer, and an expired earlier
answer MUST NOT be used in its place.

A pool whose venue has no catalogue source MUST refuse the save with its own
distinct error and MUST NOT be treated as a pool that accepts any pair.

#### Scenario: The venue is unreachable during a registration

- GIVEN pool `(binance, usdt-m, USDT)` whose venue catalogue cannot be read
- WHEN a strategy is created on pool `(binance, usdt-m, USDT)` with allowed pairs `{ETHUSDT}`
- THEN the creation is refused with the catalogue-unavailable error, no strategy row is created, and the failure is logged

#### Scenario: The venue is unreachable while a pair is being added

- GIVEN strategy S1 on pool `(binance, usdt-m, USDT)` with allowed pairs `{ETHUSDT}`, and the venue's catalogue cannot be read
- WHEN S1's list is replaced with `{ETHUSDT, STXUSDT}`
- THEN the replacement is refused with the catalogue-unavailable error and S1's allowed pairs remain `{ETHUSDT}`

#### Scenario: A listing with no available pair is unreadable, not empty

- GIVEN pool `(bybit, usdt-m, USDT)` and a venue catalogue that answers a non-empty listing in which no entry is a trading perpetual settled in `USDT`
- WHEN a strategy is created on pool `(bybit, usdt-m, USDT)` with allowed pairs `{ETHUSDT}`
- THEN the creation is refused with the catalogue-unavailable error, not with an unknown-pair error, and one ERROR is logged

#### Scenario: A pool with no catalogue source refuses the save

- GIVEN an enabled pool `(pionex, spot, USDT)`, whose venue has no catalogue source
- WHEN a strategy is created on pool `(pionex, spot, USDT)` with allowed pairs `{BTC_USDT}`
- THEN the creation is refused with the catalogue-not-served error and no strategy row is created

### Requirement: Existing Strategies' Allowed Pairs Are Seeded Once From History

The migration that introduces the allowed-pairs list MUST seed each existing
strategy's initial list from the distinct `market_key`-normalized symbols
found in the signals that strategy has already received, and MUST log what
it seeded for each strategy. This seeding MUST run exactly once, at
migration time, not on every deploy.

#### Scenario: A strategy with prior signals is seeded from its own history

- GIVEN strategy S1 has previously received signals for `ETHUSDT` and `ETHUSDT.P` (same canonical pair) and `SOLUSDT`
- WHEN the seeding migration runs
- THEN S1's allowed-pairs list is seeded with `{ETHUSDT, SOLUSDT}` and the seeded set is logged

#### Scenario: A strategy with no prior signals is seeded with an empty list

- GIVEN strategy S2 has received no signals
- WHEN the seeding migration runs
- THEN S2's allowed-pairs list is seeded empty, and the owner is expected to add pairs before S2's next signal is accepted

### Requirement: Allowed-Pairs Edits Do Not Rewrite Historical Stats

> **Revised 2026-09-24 (design finding F4).** Pairs are keyed by the
> `market_key()` of each allocation's fills, not by the raw
> `ledger_entries.symbol`, because a booked close is written under the market
> key while its open may carry `.P`.

Per-pair statistics MUST be computed from the ledger, grouped per allocation
and then by the `market_key()` of that allocation's fills, independent of the
strategy's current allowed-pairs list. Removing a pair from the allowlist MUST
NOT remove or hide that pair's historical statistics.

#### Scenario: Historical stats survive removal from the allowlist

- GIVEN strategy S1 has closed trades on `SOLUSDT` and `SOLUSDT` is later removed from S1's allowed-pairs list
- WHEN S1's per-pair statistics are read
- THEN `SOLUSDT`'s historical statistics still appear

### Requirement: Archive Requires Disabled and Flat

A strategy MUST be archivable only when it is disabled AND holds no open
position in any pool (no non-zero net in the ledger, no live reservation).
Archiving a strategy that is enabled, or that holds an open position, MUST be
refused with a reason naming which condition is unmet.

#### Scenario: Archiving a disabled, flat strategy succeeds

- GIVEN strategy S1 is disabled and holds no open position in pool `(bybit, usdt-m, USDT)`
- WHEN archive is requested for S1
- THEN S1's `archived_at` is set and the archive succeeds

#### Scenario: Archiving an enabled strategy is refused

- GIVEN strategy S1 is enabled
- WHEN archive is requested for S1
- THEN the request is refused, naming that S1 is still enabled, and `archived_at` remains unset

#### Scenario: Archiving a disabled strategy with an open position is refused

- GIVEN strategy S1 is disabled but holds a non-zero net position on `ETHUSDT` in pool `(bybit, usdt-m, USDT)`
- WHEN archive is requested for S1
- THEN the request is refused, naming that S1 holds an open position, and `archived_at` remains unset

### Requirement: Archive Is Terminal — Never Deleted, Never Reversed

A strategy row MUST NEVER be deleted by archiving. Once `archived_at` is set,
it MUST NEVER be cleared; there is no un-archive operation.

#### Scenario: Archived strategy row still exists and is readable

- GIVEN strategy S1 has been archived
- WHEN S1's detail is requested by id
- THEN S1's row is returned, including its `archived_at` timestamp and full history

#### Scenario: No operation clears archived_at

- GIVEN strategy S1 is archived
- WHEN any update request for S1 is submitted
- THEN no request clears `archived_at`, and any request attempting to do so is refused

### Requirement: Enabling An Archived Strategy Is Refused

An update that would set an archived strategy's `enabled` to true MUST be
refused.

#### Scenario: Enabling an archived strategy is refused

- GIVEN strategy S1 is archived
- WHEN an enable request is submitted for S1
- THEN the request is refused and S1's `enabled` value is unchanged

### Requirement: Archived Strategy's Signals Are Persisted Then Refused, No Ingress Lookup

A signal for an archived strategy MUST be persisted by the webhook exactly as
any other signal, with no additional database lookup added to the ingress
path. During processing, that signal MUST be refused with exactly one
WARNING naming the strategy and instructing the owner to remove the
TradingView alert. The signal MUST NOT create a reservation in any pool.

#### Scenario: Webhook persists an archived strategy's signal unchanged

- GIVEN strategy S1 is archived
- WHEN a webhook request for S1 arrives with a valid idempotency key
- THEN the signal is persisted and a job is enqueued exactly as for a non-archived strategy, with no strategy lookup performed at ingress

#### Scenario: Processing refuses the archived strategy's signal

- GIVEN a persisted signal for archived strategy S1 bound to pool `(bybit, usdt-m, USDT)`
- WHEN the signal is processed
- THEN it is refused, no reservation is created against pool `(bybit, usdt-m, USDT)`, and exactly one WARNING is logged naming S1 and instructing the owner to remove the alert

### Requirement: Enable/Disable Event Log

> **Revised 2026-09-24 (design finding F8).** The admin API cannot create an
> enabled strategy: `POST /api/strategies` has no `enabled` field and every new
> strategy starts disabled. The former "creating enabled writes the first
> event" scenario could not occur and is replaced below.

Every actual change to a strategy's `enabled` value MUST append exactly one
event to an append-only enable/disable event log, in the same transaction as
the `enabled` write. A PATCH that does not change the effective `enabled`
value MUST write no event. Creating a strategy (always disabled) MUST write no
event; its first enable writes its first event.

#### Scenario: Toggling enabled twice writes two events

- GIVEN strategy S1 is currently enabled
- WHEN S1 is disabled and then re-enabled
- THEN exactly two events are written: one disable event and one enable event, each in the same transaction as its `enabled` write

#### Scenario: A no-op PATCH writes no event

- GIVEN strategy S1 is currently enabled
- WHEN an update request sets `enabled=true` again (no change)
- THEN no new event is written

#### Scenario: Creation writes no event and the first enable writes the first one

- GIVEN a new strategy is created through the admin API, and is therefore disabled
- WHEN creation completes and the strategy is later enabled for the first time
- THEN no event exists after creation, and exactly one enable event exists after that first enable, timestamped at the enable

### Requirement: Cumulative Uptime Is Derived, Never Stored As a Running Total

A strategy's cumulative uptime MUST be computed by summing the intervals
between paired enable/disable events from the event log, including the
still-open interval if the strategy is currently enabled. Uptime MUST NEVER
be persisted as a stored running total that could drift from the event log.

#### Scenario: Uptime sums closed and open intervals

- GIVEN strategy S1 was enabled for 3 days, disabled for 1 day, then re-enabled and has been enabled for 2 more days as of now
- WHEN S1's cumulative uptime is computed
- THEN it equals 5 days, summed from the event log, with no stored total read

#### Scenario: A strategy never enabled has zero uptime

- GIVEN strategy S2 was created disabled and has never been enabled
- WHEN S2's cumulative uptime is computed
- THEN it is zero and no first-activation date is shown

### Requirement: Strategy Listing Excludes Archived By Default

The default strategy list MUST exclude archived strategies. An archived
strategy's detail view MUST still load by id.

#### Scenario: Default list omits archived strategies

- GIVEN strategy S1 is archived and strategy S2 is not
- WHEN the default strategy list is read
- THEN S2 appears and S1 does not

#### Scenario: Archived strategy detail still loads

- GIVEN strategy S1 is archived
- WHEN S1's detail is requested directly by id
- THEN S1's full detail, including `archived_at`, is returned
