# Admin API Specification

## Purpose

The `/api` namespace is the entire administrative surface the operator panel
consumes: strategies, pools/balances, performance reads, credentials, and
reconciliation/booking. It requires the existing bearer token on every route.
`/webhook/tradingview` and `/health` are not part of this namespace and are
unaffected by it.

> **Revised 2026-09-25 (owner decision 23).** Adds a dedicated endpoint
> contract for the webhook shared secret: its own route, called only on
> explicit request, never echoed by any other route or logged.
>
> **Revised 2026-10-02 (owner decisions 40 and 41).** Adds the refusals of the
> two strategy save endpoints for a pair the pool's venue does not list, and a
> read endpoint for a pool's available pairs. Both are the last two
> requirements of this file.
>
> **Revised 2026-10-02 (owner decision 42).** Adds `DELETE /api/strategies/{id}`
> for a strategy with no history. It is the last requirement of this file.
>
> **Revised 2026-10-04 (owner decision 43, design addendum "decision 43" §
> D).** `GET /api/performance/strategies/{id}/trades` gains one query parameter
> and eight fields per row, and a new read, `GET
> /api/performance/strategies/{id}/trades/{allocation_id}/fills`, serves one
> operation's fills. Three requirements are added after the delete requirement;
> no existing requirement of this file is changed.

## Requirements

### Requirement: Every Admin Route Is Mounted Under /api

Every administrative HTTP route (strategies, reconciliation/booking, pools,
performance, credentials) MUST be mounted under the `/api` path prefix.

#### Scenario: Strategy routes live under /api

- GIVEN the application is running
- WHEN a request is made to `GET /api/strategies`
- THEN it is routed to the strategies admin handler

#### Scenario: A pre-move path no longer resolves to an admin route

- GIVEN the `/api` move has been applied
- WHEN a request is made to `GET /strategies` (the pre-move path)
- THEN it is not routed to the strategies admin handler

### Requirement: Webhook and Health Are Not Under /api

`/webhook/tradingview` and `/health` MUST remain at their existing paths,
unaffected by the `/api` move.

#### Scenario: Webhook path is unchanged

- GIVEN the `/api` move has been applied
- WHEN a request is made to `POST /webhook/tradingview`
- THEN it behaves exactly as it did before the move

#### Scenario: Health path is unchanged

- GIVEN the `/api` move has been applied
- WHEN a request is made to `GET /health`
- THEN it responds exactly as it did before the move

### Requirement: Every Admin Route Requires the Bearer Token

Every route under `/api` MUST require the existing `ADMIN_API_TOKEN` bearer
token, checked before handler logic runs. This includes every newly added
route (pools/balances, performance, strategy stats, allowed-pairs edit,
archive, credential list/add/rotate) in addition to existing strategy and
reconciliation routes.

#### Scenario: A request with no bearer token is refused

- GIVEN no bearer token is supplied
- WHEN any `/api` route is called
- THEN the request is refused before handler logic executes

#### Scenario: A request with a valid bearer token is admitted

- GIVEN the correct `ADMIN_API_TOKEN` bearer token is supplied
- WHEN an `/api` route is called
- THEN the request reaches handler logic

#### Scenario: The webhook route requires no bearer token

- GIVEN a valid TradingView webhook request per signal-ingress's own authentication
- WHEN `POST /webhook/tradingview` is called
- THEN it is not required to carry the `ADMIN_API_TOKEN` bearer token

### Requirement: The Webhook Shared Secret Is Returned Only By Its Own Endpoint

> **Added 2026-09-25 (owner decision 23).**

The webhook shared secret (`WEBHOOK_SECRET`) MUST be returned only by a
dedicated `GET /api/webhook-secret` route, requiring the same bearer token as
every other `/api` route. No other `/api` response body, of any route, MUST
ever include the secret's value. The response MUST carry
`Cache-Control: no-store`. Access logging MUST NOT record the secret's value.

#### Scenario: The dedicated endpoint returns the secret with no-store

- GIVEN a valid bearer token
- WHEN `GET /api/webhook-secret` is called
- THEN it returns the configured secret with a `Cache-Control: no-store` response header

#### Scenario: No other route ever carries the secret

- GIVEN the configured webhook secret has a known value
- WHEN every other `/api` route's response bodies are inspected, including strategy and credential listings
- THEN none of them contain that value

#### Scenario: The secret is never written to the access log

- GIVEN `GET /api/webhook-secret` is called and logged by the access-log middleware
- WHEN the resulting log line is inspected
- THEN it does not contain the secret's value


### Requirement: The Credential Endpoints Carry The Owner Confirmations And The Recorded Facts

> **Added 2026-09-29 (owner decisions 24 and 30).**

`PUT /api/credentials/{exchange}` MUST accept the key, the secret, an optional
label, and two booleans that default to false: `withdrawals_disabled_confirmed`
and `futures_enabled_confirmed`. For Binance both MUST be true, and a missing
or false one MUST answer 422 `CONFIRMATION_REQUIRED` naming exactly what is
absent, before the venue is called. For Bybit a true value MUST answer 422
`CONFIRMATION_NOT_APPLICABLE` naming the field. A client MUST NOT be able to
supply a confirmation time; the server stamps it.

`GET /api/credentials` MUST return, per exchange, `exchange`, `status`,
`last4`, `label`, `stored_at`, `validated_at`, `trade_capable`,
`trade_capability_source`, `trade_confirmed_at`, `withdraw_check`,
`withdraw_confirmed_at` and `internal_transfer`, all null for an `EMPTY`
exchange. It MUST NOT return a raw permission payload or a `permissions` field.

#### Scenario: A Binance save missing a confirmation is refused naming it

- GIVEN a valid bearer token and a Binance body with `futures_enabled_confirmed` false
- WHEN `PUT /api/credentials/binance` is called
- THEN it answers 422 `CONFIRMATION_REQUIRED` with `missing` naming `futures_enabled_confirmed`, and nothing is sent to Binance

#### Scenario: A Bybit save with a true confirmation is refused

- GIVEN a valid bearer token and a Bybit body with `withdrawals_disabled_confirmed` true
- WHEN `PUT /api/credentials/bybit` is called
- THEN it answers 422 `CONFIRMATION_NOT_APPLICABLE` naming that field

#### Scenario: The listing carries the recorded facts and no permissions field

- GIVEN a valid bearer token and an active Binance credential saved with both confirmations
- WHEN `GET /api/credentials` is called
- THEN the Binance entry carries its sources and both confirmation times, and no entry has a `permissions` field

### Requirement: The Strategy Save Endpoints Refuse Pairs The Pool's Venue Does Not List

> **Added 2026-10-02 (owner decisions 40 and 41).**

`POST /api/strategies` and `PUT /api/strategies/{id}/allowed-pairs` MUST answer
a structured refusal, carried in the response's `detail` object with an `error`
code and a `message`, in each of these cases. In every case nothing MUST be
stored.

- A pair that is not available to the strategy's capital pool `(exchange,
  venue, settlement_currency)` MUST answer 422 `UNKNOWN_PAIRS` with an
  `unknown` list naming every such pair in `market_key()` form, sorted. On
  `POST` every submitted pair is checked; on `PUT` only the pairs not already
  stored are.
- A pool whose venue catalogue cannot be read MUST answer 502
  `PAIR_CATALOGUE_UNAVAILABLE`.
- A pool whose venue has no catalogue source MUST answer 422
  `PAIR_CATALOGUE_NOT_SERVED`.
- On `PUT`, a stored list that changed during the request so that an
  unvalidated pair would become an addition MUST answer 409 `PAIRS_CHANGED`.

The refusals that existed before (404, 409 `STRATEGY_ARCHIVED`, 409 for a
duplicate, 422 for an empty list or an unavailable pool) MUST keep their
status and shape.

#### Scenario: A registration with an unlisted symbol names it

- GIVEN a valid bearer token and pool `(bybit, usdt-m, USDT)` whose available pairs include `ETHUSDT` and not `YPF`
- WHEN `POST /api/strategies` is called for pool `(bybit, usdt-m, USDT)` with `allowed_pairs` `["ETHUSDT", "YPF"]`
- THEN it answers 422 with `detail.error` `UNKNOWN_PAIRS` and `detail.unknown` `["YPF"]`, and no strategy exists afterwards

#### Scenario: A replacement that adds an unlisted symbol names it

- GIVEN a valid bearer token and strategy S1 on pool `(bybit, usdt-m, USDT)` with allowed pairs `{ETHUSDT}`
- WHEN `PUT /api/strategies/{S1}/allowed-pairs` is called with `pairs` `["ETHUSDT", "BTC"]` and `BTC` is not available to that pool
- THEN it answers 422 with `detail.error` `UNKNOWN_PAIRS` and `detail.unknown` `["BTC"]`, and S1's allowed pairs are unchanged

#### Scenario: A replacement keeping a delisted stored pair is accepted

- GIVEN a valid bearer token and strategy S1 on pool `(bybit, usdt-m, USDT)` with allowed pairs `{ETHUSDT, SFPUSDT}`, where `SFPUSDT` is no longer available to that pool
- WHEN `PUT /api/strategies/{S1}/allowed-pairs` is called with `pairs` `["ETHUSDT", "SFPUSDT"]`
- THEN it answers 200 with allowed pairs `["ETHUSDT", "SFPUSDT"]`

#### Scenario: An unreachable venue is a 502, not a 422

- GIVEN a valid bearer token and pool `(binance, usdt-m, USDT)` whose venue catalogue cannot be read
- WHEN `POST /api/strategies` is called for pool `(binance, usdt-m, USDT)` with `allowed_pairs` `["ETHUSDT"]`
- THEN it answers 502 with `detail.error` `PAIR_CATALOGUE_UNAVAILABLE`, and no strategy exists afterwards

### Requirement: A Pool's Available Pairs Are Readable

> **Added 2026-10-02 (owner decisions 40 and 41).**

`GET /api/pools/{exchange}/{venue}/{settlement_currency}/available-pairs` MUST
return the pairs available to that capital pool as `{pool: {exchange, venue,
settlement_currency}, pairs, count}`, with `pairs` sorted and in `market_key()`
form, which is the form the save endpoints accept back. It MUST require the
bearer token like every other `/api` route. It MUST answer for a pool that
exists and is disabled. It MUST NOT answer an empty list in place of an error:

- a triple that is not a configured capital pool MUST answer 404, and MUST NOT
  cause the venue to be read;
- a pool whose venue has no catalogue source MUST answer 404 with `detail.error`
  `PAIR_CATALOGUE_NOT_SERVED`;
- a pool whose venue catalogue cannot be read MUST answer 502 with
  `detail.error` `PAIR_CATALOGUE_UNAVAILABLE`.

The response MUST NOT contain a balance, a credential, or any other pool's
pairs.

#### Scenario: The available pairs of a pool are returned sorted

- GIVEN a valid bearer token and pool `(bybit, usdt-m, USDT)` whose venue lists the trading USDT perpetuals `STXUSDT` and `AAVEUSDT`
- WHEN `GET /api/pools/bybit/usdt-m/USDT/available-pairs` is called
- THEN it answers 200 with `pairs` `["AAVEUSDT", "STXUSDT"]`, `count` 2, and `pool` naming `(bybit, usdt-m, USDT)`

#### Scenario: The read requires the bearer token

- GIVEN no bearer token is supplied
- WHEN `GET /api/pools/bybit/usdt-m/USDT/available-pairs` is called
- THEN the request is refused before the venue is read

#### Scenario: An unknown pool is a 404 and reads no venue

- GIVEN a valid bearer token and no configured pool `(bybit, usdt-m, BTC)`
- WHEN `GET /api/pools/bybit/usdt-m/BTC/available-pairs` is called
- THEN it answers 404 and no request is sent to any venue

#### Scenario: A disabled pool still answers

- GIVEN a valid bearer token and a configured, disabled pool `(binance, usdt-m, USDT)`
- WHEN `GET /api/pools/binance/usdt-m/USDT/available-pairs` is called
- THEN it answers 200 with that pool's available pairs

#### Scenario: A pool with no catalogue source is not an empty list

- GIVEN a valid bearer token and a configured pool `(pionex, spot, USDT)`, whose venue has no catalogue source
- WHEN `GET /api/pools/pionex/spot/USDT/available-pairs` is called
- THEN it answers 404 with `detail.error` `PAIR_CATALOGUE_NOT_SERVED`, not a 200 with an empty `pairs`

#### Scenario: An unreachable venue is a 502

- GIVEN a valid bearer token and pool `(binance, usdt-m, USDT)` whose venue catalogue cannot be read
- WHEN `GET /api/pools/binance/usdt-m/USDT/available-pairs` is called
- THEN it answers 502 with `detail.error` `PAIR_CATALOGUE_UNAVAILABLE`

#### Scenario: Two pools never share an answer

- GIVEN a valid bearer token and pools `(bybit, usdt-m, USDT)` and `(binance, usdt-m, USDT)` whose venues list different pairs
- WHEN each pool's available pairs are read, one after the other
- THEN each response holds only its own pool's pairs

### Requirement: A Strategy With No History Is Deleted Through Its Own Endpoint

> **Added 2026-10-02 (owner decision 42).**

`DELETE /api/strategies/{id}` MUST delete a strategy that is disabled and has
no history (strategy-lifecycle, "A Strategy With No History Can Be Deleted"),
and MUST answer 204 with no body. It MUST require the bearer token like every
other `/api` route. It MUST contact no venue and MUST behave identically with
`DRY_RUN` true or false.

Every refusal MUST say why, in the response's `detail`, and MUST change
nothing:

- an id under which no strategy is registered MUST answer 404, including a
  repeated delete of a strategy already deleted;
- a strategy that is enabled MUST answer 409 with `detail.error`
  `STILL_ENABLED`, the code the archive endpoint uses;
- a strategy with any history MUST answer 409 with `detail.error`
  `HAS_HISTORY` and a `detail.history` object that always carries the six
  integer counts `signals`, `reservations`, `execution_attempts`,
  `ledger_entries`, `booking_proposals` and `enablement_events`, counted across
  every capital pool `(exchange, venue, settlement_currency)`. Enablement
  events are reported but are not history: they never cause a refusal on their
  own, and a strategy that has only them is deleted with them;
- a delete the database refuses although every count is zero MUST answer 409
  `HAS_HISTORY` too, never a 5xx.

No response of this endpoint MUST contain a credential, a balance, or a sum of
money across pools. The refusals of the other strategy endpoints MUST keep
their status and shape.

> **Decided 2026-10-02 (owner decision 42, design addendum 9x § L, Q3).** An
> archived strategy with no history is deleted like any other disabled one.
>
> **Decided 2026-10-02 (owner decision 42, design addendum 9x § L, Q1).**
> Enablement events do not block the delete (migration 0028).

#### Scenario: A disabled strategy with no history is deleted

- GIVEN a valid bearer token and strategy S1 on pool `(bybit, usdt-m, USDT)`, disabled, never enabled, with no signal
- WHEN `DELETE /api/strategies/{S1}` is called
- THEN it answers 204 with no body, and `GET /api/strategies/{S1}` answers 404 afterwards

#### Scenario: The delete requires the bearer token

- GIVEN no bearer token is supplied
- WHEN `DELETE /api/strategies/{S1}` is called
- THEN the request is refused and S1 still exists

#### Scenario: An unknown id is a 404

- GIVEN a valid bearer token and no strategy registered under id X
- WHEN `DELETE /api/strategies/{X}` is called
- THEN it answers 404

#### Scenario: A repeated delete is a 404

- GIVEN a valid bearer token and strategy S1 was deleted by a previous call
- WHEN `DELETE /api/strategies/{S1}` is called again
- THEN it answers 404

#### Scenario: An enabled strategy is a 409 that says so

- GIVEN a valid bearer token and strategy S1 is enabled
- WHEN `DELETE /api/strategies/{S1}` is called
- THEN it answers 409 with `detail.error` `STILL_ENABLED`, and S1 still exists and is still enabled

#### Scenario: A strategy with history is a 409 that names each kind with its count

- GIVEN a valid bearer token and strategy S1 on pool `(bybit, usdt-m, USDT)`, disabled, with 3 signals, 1 reservation, 1 execution attempt and 2 ledger entries
- WHEN `DELETE /api/strategies/{S1}` is called
- THEN it answers 409 with `detail.error` `HAS_HISTORY` and `detail.history` `{"signals": 3, "reservations": 1, "execution_attempts": 1, "ledger_entries": 2, "booking_proposals": 0, "enablement_events": 0}`, and S1 and all seven rows still exist

#### Scenario: A strategy that was only ever toggled is deleted with its events

- GIVEN a valid bearer token and strategy S1, disabled, with no signal and 2 enablement events
- WHEN `DELETE /api/strategies/{S1}` is called
- THEN it answers 204 with no body, and `GET /api/strategies/{S1}` answers 404 afterwards

#### Scenario: Events do not hide the other history

- GIVEN a valid bearer token and strategy S1, disabled, with 1 signal and 2 enablement events
- WHEN `DELETE /api/strategies/{S1}` is called
- THEN it answers 409 with `detail.error` `HAS_HISTORY` and `detail.history` carrying `signals` 1 and `enablement_events` 2, and S1, the signal and both events still exist

#### Scenario: After a delete the strategy's other routes answer 404

- GIVEN a valid bearer token and strategy S1 was deleted
- WHEN `GET /api/strategies/{S1}/events`, `GET /api/performance/strategies/{S1}` and `POST /api/strategies/{S1}/archive` are called
- THEN each answers 404

#### Scenario: A deleted id can be registered again

- GIVEN a valid bearer token and strategy S1 on pool `(bybit, usdt-m, USDT)` was deleted
- WHEN `POST /api/strategies` is called with S1's id and name for pool `(bybit, usdt-m, USDT)`
- THEN it answers 201 with a disabled strategy whose `uptime.seconds` is 0 and whose `uptime.first_enabled_at` is null

### Requirement: The Trades Route Serves Each Operation's Figures

> **Added 2026-10-04 (owner decision 43).**

`GET /api/performance/strategies/{id}/trades` MUST keep its existing query
parameters (`limit` 1..200 with default 50, and `before_closed_at` with
`before_allocation_id`, both or neither), its existing fields, its ordering and
its `next_cursor`, and MUST serve eight new fields on each row of `trades`. The
route MUST require the bearer token like every other `/api` route. Every
operation is in the strategy's own pool, and no field of the response is a
total across operations or pools.

Each row MUST carry, in addition to `allocation_id`, `pair`, `direction`,
`opened_at`, `closed_at`, `pnl`, `capital_at_open`, `return` and
`fees_complete`:

| Field | Type | Null |
| --- | --- | --- |
| `rehearsal` | boolean | never; false on a real row and on every row of a request that did not ask for rehearsal rows |
| `rehearsal_fill_price` | string `"FIXED_ONE"`, `"ALERT"` or `"UNDETERMINED"` | exactly when `rehearsal` is false |
| `base_currency` | string, upper case | together with `entry_price`, `exit_price` and `size`, when they cannot be derived from the operation's fills |
| `entry_price` | string, 18 decimal places | as `base_currency` |
| `exit_price` | string, 18 decimal places | as `base_currency` |
| `size` | string, base units | as `base_currency` |
| `fees` | string, settlement currency | never |
| `other_fees` | list of `{currency, amount}` | never; empty when none |

`other_fees` entries MUST carry an upper-cased `currency` string and an
`amount` string above zero, in that currency, unconverted. The four nullable
figures MUST be null together or not at all, and null MUST mean "cannot be
derived from this operation's fills", never zero. Money, quantities, prices and
ratios MUST be JSON strings in plain notation, never a JSON number and never an
exponent. A price is rounded half-even to 18 decimal places. `capital_at_open`
and `return` stay null for an operation opened before the pool capital was
recorded.

The route MUST keep its refusals: 404 `no such strategy` for an unknown id, and
422 for half a cursor, a `before_closed_at` without a zone, or a `limit`
outside 1..200. A request with none of the new parameters MUST receive the same
rows, in the same order, as before, with the eight new fields added.

#### Scenario: A closed real operation carries every new field

- GIVEN a valid bearer token and strategy S1 on pool `(bybit, usdt-m, USDT)` with one closed LONG that bought 1250 `STXUSDT.P` at 0.4512 and sold 1250 `STXUSDT` at 0.4631, fees 0.31 USDT and 0.32 USDT
- WHEN `GET /api/performance/strategies/{S1}/trades` is called
- THEN the row has `pair` `"STXUSDT"`, `rehearsal` false, `rehearsal_fill_price` null, `base_currency` `"STX"`, `entry_price` `"0.451200000000000000"`, `exit_price` `"0.463100000000000000"`, `size` `"1250.000000000000000000"`, `fees` `"0.630000000000000000"`, `other_fees` `[]` and `pnl` `"14.245000000000000000"`

#### Scenario: A fee in another currency is listed with its own currency

- GIVEN a valid bearer token and a closed operation on pool `(binance, usdt-m, USDT)` that paid 0.00012 BNB
- WHEN the trades route is called for its strategy
- THEN `other_fees` is `[{"currency": "BNB", "amount": "0.000120000000000000"}]` and `fees_complete` is false

#### Scenario: Figures that cannot be derived are null together and the row is still served

- GIVEN a valid bearer token and a closed operation whose fills name `STXUSDT` and `SOLUSDT`
- WHEN the trades route is called
- THEN the row is present with `base_currency`, `entry_price`, `exit_price` and `size` all null, `fees` a string, `other_fees` a list, and `pnl` unchanged

#### Scenario: No response field is a JSON number or an exponent

- GIVEN a valid bearer token and a strategy with real and rehearsal rows
- WHEN every response of the trades route and of the fills route is walked
- THEN no value is a JSON float and no string carries an exponent

#### Scenario: The trades route requires the bearer token

- GIVEN no bearer token is supplied
- WHEN `GET /api/performance/strategies/{S1}/trades` is called
- THEN the request is refused before handler logic executes

#### Scenario: The existing refusals are unchanged

- GIVEN a valid bearer token
- WHEN the route is called with an unknown strategy id, with `before_closed_at` only, with a `before_closed_at` lacking a zone, and with `limit=201`
- THEN it answers 404 `no such strategy`, 422, 422 and 422 respectively

### Requirement: The Trades Route Serves Rehearsal Operations Only When Asked

> **Added 2026-10-04 (owner decision 43, answered 2026-10-03).**

`GET /api/performance/strategies/{id}/trades` MUST accept a boolean query
parameter `include_rehearsal`, default false. Without it, or with false, the
response MUST contain no rehearsal row. With true, it MUST also contain the
strategy's closed rehearsal operations, each with `rehearsal` true and a
non-null `rehearsal_fill_price`, in the one list and order of the real rows,
and the existing cursor MUST work unchanged across both kinds. A value that is
not a boolean MUST be refused with 422. The parameter MUST NOT change any other
route's response.

#### Scenario: The default request holds no rehearsal row

- GIVEN a valid bearer token and strategy S1 with one real closed operation and one closed rehearsal operation
- WHEN `GET /api/performance/strategies/{S1}/trades` is called without `include_rehearsal`
- THEN `trades` holds the real operation only

#### Scenario: The opted-in request holds both kinds, marked

- GIVEN the same strategy S1
- WHEN `GET /api/performance/strategies/{S1}/trades?include_rehearsal=true` is called
- THEN `trades` holds both, the rehearsal row with `rehearsal` true and `rehearsal_fill_price` one of the three values, the real row with `rehearsal` false and `rehearsal_fill_price` null

#### Scenario: A rehearsal row's classification is served as stored data implies

- GIVEN a rehearsal operation whose opening fill is priced 1 against an alert that carried 0.4512, size 12.5, and whose closing fill is priced 1 with no fee
- WHEN the opted-in trades request is made
- THEN its row has `rehearsal_fill_price` `"FIXED_ONE"`, `entry_price` `"1.000000000000000000"` and `pnl` `"0.000000000000000000"`

(Revised 2026-10-04, owner decision 45. Previously the GIVEN fixed only the opening fill. `pnl` 0 follows only when the closing fill is also priced 1 with no fee; the next scenario covers a closing fill that is not.)

#### Scenario: A position that straddles decision 45 is FIXED_ONE with a non-zero PnL

- GIVEN a LONG rehearsal operation in pool `(bybit, usdt-m, USDT)` whose opening fill, written before decision 45 took effect, bought 1250 `STXUSDT` at price 1 with no fee against an alert that carried 0.4512, and whose closing fill, written after it, sold 1250 `STXUSDT` at 0.4633 with fee 0.31851875 USDT
- WHEN the opted-in trades request is made
- THEN its row has `rehearsal` true, `rehearsal_fill_price` `"FIXED_ONE"`, `entry_price` `"1.000000000000000000"`, `exit_price` `"0.463300000000000000"`, `fees` `"0.318518750000000000"` and `pnl` `"-671.193518750000000000"`

#### Scenario: A strategy that only ran in dry run lists its operations

- GIVEN a valid bearer token and strategy S1 whose ledger holds one closed rehearsal round trip
- WHEN the opted-in trades request is made, and then `GET /api/performance/strategies/{S1}` is called
- THEN `trades` holds one row marked `rehearsal` true, and the strategy report shows 0 trades and 0 PnL

#### Scenario: The cursor pages across both kinds

- GIVEN 3 real and 2 rehearsal closed operations for S1 and `limit=2`
- WHEN the opted-in request is followed through `next_cursor` until it is null
- THEN the 5 operations are served exactly once each, in close-instant descending order with ties by allocation id descending, and `next_cursor` is null on the last page only

#### Scenario: A value that is not a boolean is refused

- GIVEN a valid bearer token
- WHEN the route is called with `include_rehearsal=maybe`
- THEN it answers 422

### Requirement: One Operation's Fills Are Served By Their Own Route

> **Added 2026-10-04 (owner decision 43, answered 2026-10-04).**

`GET /api/performance/strategies/{id}/trades/{allocation_id}/fills` MUST
return `{allocation_id, fills, truncated}` where `allocation_id` is the id
asked for, `fills` is a non-empty list, and `truncated` is a boolean, none
ever null. Each fill MUST carry `filled_at` (a UTC instant), `side` (`"BUY"`
or `"SELL"`), `price`, `quantity`, `fee` (strings, the stored values, `fee` may
be zero), `fee_currency` (an upper-cased string) and `rehearsal` (a boolean),
none ever null. It MUST NOT carry the USD rate, venue order or fill ids,
notional or symbol. Fills MUST be ordered by instant ascending, ties by row id,
and MUST be capped at 200 with `truncated` true only when more existed. The
route MUST require the bearer token like every other `/api` route, MUST need no
opt-in parameter for a rehearsal operation, and MUST answer for an operation
that is closed or still open.

The route MUST answer:

| Case | Status | Body |
| --- | --- | --- |
| Fills found | 200 | as above |
| No strategy under `{id}` | 404 | `{"detail": "no such strategy"}` |
| No fill carries both this allocation id and this strategy's id | 404 | `{"detail": "no such operation"}` |
| `allocation_id` is not a UUID | 422 | the framework's own |
| A fill of this allocation and strategy sits in another pool than the strategy's | 500 | `performance data failed an integrity check`, and no fill |

The 404 `no such operation` MUST be identical in status and body for an
allocation id that does not exist, an allocation of ANOTHER strategy, and an
allocation of this strategy that never had a fill, and MUST NOT reveal whether
the id exists elsewhere.

#### Scenario: The fills of a closed operation are served

- GIVEN a valid bearer token and strategy S1 on pool `(bybit, usdt-m, USDT)` with a closed operation A1 whose BUY of 1250 at 0.4512 (fee 0.31 USDT) preceded its SELL of 1250 at 0.4631 (fee 0.32 USDT)
- WHEN `GET /api/performance/strategies/{S1}/trades/{A1}/fills` is called
- THEN it answers 200 with `allocation_id` A1, two fills ordered BUY then SELL, the first `{"side": "BUY", "price": "0.451200000000000000", "quantity": "1250.000000000000000000", "fee": "0.310000000000000000", "fee_currency": "USDT", "rehearsal": false}`, and `truncated` false

#### Scenario: A rehearsal operation's fills are served without an opt-in

- GIVEN a valid bearer token and a closed rehearsal operation A3 of S1
- WHEN `GET /api/performance/strategies/{S1}/trades/{A3}/fills` is called
- THEN it answers 200 and every fill has `rehearsal` true

#### Scenario: A mixed allocation answers every fill with its own flag

- GIVEN a valid bearer token and an allocation of S1 with 2 real and 2 rehearsal fills
- WHEN its fills route is called
- THEN it answers 200 with 4 fills, 2 with `rehearsal` true and 2 with false

#### Scenario: Both spellings of an operation's symbol are served

- GIVEN a valid bearer token and an operation opened as `STXUSDT.P` and closed as `STXUSDT`
- WHEN its fills route is called
- THEN the fills of both spellings are in the answer

#### Scenario: More than 200 fills are cut and flagged

- GIVEN a valid bearer token and an operation with 201 fills
- WHEN its fills route is called
- THEN it answers 200 with 200 fills and `truncated` true

#### Scenario: An unknown id, another strategy's operation and an empty one answer the same 404

- GIVEN a valid bearer token, strategies S1 and S2 in the same pool, S2's allocation A2, and S1's reservation R1 that never had a fill
- WHEN S1's fills route is called for a random UUID, for A2, and for R1
- THEN each answers 404 with the body `{"detail": "no such operation"}`, and no fill of A2 is in any body

#### Scenario: An unknown strategy is a different 404

- GIVEN a valid bearer token and no strategy under id X
- WHEN `GET /api/performance/strategies/{X}/trades/{A1}/fills` is called
- THEN it answers 404 with the body `{"detail": "no such strategy"}`

#### Scenario: An allocation id that is not a UUID is a 422

- GIVEN a valid bearer token
- WHEN the fills route is called with `allocation_id` `not-a-uuid`
- THEN it answers 422

#### Scenario: A fill in another pool answers the integrity failure

- GIVEN a valid bearer token and an allocation of S1 with a fill written under a pool other than S1's
- WHEN its fills route is called
- THEN it answers 500 `performance data failed an integrity check` with no fill in the body

#### Scenario: The fills route requires the bearer token

- GIVEN no bearer token is supplied
- WHEN `GET /api/performance/strategies/{S1}/trades/{A1}/fills` is called
- THEN the request is refused before handler logic executes
