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
>
> **Revised 2026-10-06 (owner decisions 44 and 48, design addendum "unit
> 12f").** The strategy view and `PATCH /api/strategies/{id}` carry the share of
> the pool per trade in plain notation; a new read, `GET
> /api/strategies/{id}/share-preview`, serves the amount a share asks for; a
> new read, `GET /api/webhook-origin`, serves the webhook's host; and each
> `by_pair` entry of the strategy performance read gains `wins` and `win_rate`.
> Four requirements are added after "One Operation's Fills Are Served By Their
> Own Route"; no existing requirement of this file is changed. The two new
> reads and the new fields are covered by "Every Admin Route Requires the
> Bearer Token" and "The Webhook Shared Secret Is Returned Only By Its Own
> Endpoint" as written.

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

### Requirement: The Strategy Update Takes The Share As A Plain Decimal And The Strategy View Serves It In Plain Notation

> **Added 2026-10-06 (owner decisions 44 (12f.1) and 48; design addendum "unit 12f" § A U1, U2, U4 and § C).**

`PATCH /api/strategies/{id}` MUST accept `allocation_percent` as a string holding
a decimal above 0 and at most 100 with at most 18 decimal places (owner decision
50, 2026-10-09; "A Share Has At Most 18 Decimal Places" below); a value below 1
(for example `0.5`) is valid. A body that carries only `allocation_percent` MUST
leave every other field of the strategy unchanged. It MUST answer:

| Case | Status |
| --- | --- |
| A valid share on an unarchived strategy, enabled or disabled | 200 with the strategy view |
| A share of 0, above 100, not a decimal, or written with more than 18 decimal places | 422 |
| An archived strategy | 409 `STRATEGY_ARCHIVED` |
| No strategy under `{id}` | 404 |

Every body that serves the strategy view (the PATCH's answer and the GET's) MUST
write `allocation_percent` in plain decimal notation, as text, and MUST NEVER
write an exponent (`1E-7`). The PATCH's answer and a later GET MUST show the same
text for the same value. The route MUST be behind the bearer token like every
other `/api` route.

#### Scenario: A decimal share is saved and served as it is

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` with a stored share of `30`
- WHEN `PATCH /api/strategies/{S1}` is called with `{"allocation_percent": "33.5"}`
- THEN it answers 200 with a strategy view whose `allocation_percent` is `"33.5"`, and a later `GET /api/strategies/{S1}` serves `"33.5"`

#### Scenario: A share below 1 is accepted

- GIVEN strategy S1 with a stored share of `30`
- WHEN the PATCH carries `{"allocation_percent": "0.5"}`
- THEN it answers 200 and the stored share is `0.5`

#### Scenario: A share of exactly 100 is accepted

- GIVEN strategy S1 with a stored share of `30`
- WHEN the PATCH carries `{"allocation_percent": "100"}`
- THEN it answers 200

#### Scenario: Zero is refused

- GIVEN strategy S1 with a stored share of `30`
- WHEN the PATCH carries `{"allocation_percent": "0"}`
- THEN it answers 422 and the stored share is still `30`

#### Scenario: A share above 100 is refused

- GIVEN strategy S1 with a stored share of `30`
- WHEN the PATCH carries `{"allocation_percent": "100.5"}`
- THEN it answers 422 and the stored share is still `30`

#### Scenario: A text that is not a decimal is refused

- GIVEN strategy S1 with a stored share of `30`
- WHEN the PATCH carries `{"allocation_percent": "abc"}`
- THEN it answers 422 and the stored share is still `30`

#### Scenario: An archived strategy's share is refused

- GIVEN strategy S1 is archived with a stored share of `30`
- WHEN the PATCH carries `{"allocation_percent": "40"}`
- THEN it answers 409 `STRATEGY_ARCHIVED` and the stored share is still `30`

#### Scenario: A disabled strategy's share is accepted

- GIVEN strategy S1 is disabled with a stored share of `30`
- WHEN the PATCH carries `{"allocation_percent": "40"}`
- THEN it answers 200 and S1 is still disabled

#### Scenario: An unknown strategy answers 404

- GIVEN no strategy under id X
- WHEN `PATCH /api/strategies/{X}` is called with `{"allocation_percent": "40"}`
- THEN it answers 404

#### Scenario: Only the share changes

- GIVEN strategy S1 with a stored share of `30`, `enabled` true and two allowed pairs
- WHEN the PATCH carries only `{"allocation_percent": "40"}`
- THEN `enabled` is still true and the two allowed pairs are unchanged

#### Scenario: A very small share is never served with an exponent

- GIVEN strategy S1 with a stored share of `0.0000001`
- WHEN S1 is read with `GET /api/strategies/{S1}` and after a PATCH of the same value
- THEN each body carries `"allocation_percent": "0.0000001"` and neither carries `1E-7`

#### Scenario: The route requires the bearer token

- GIVEN no bearer token is supplied
- WHEN `PATCH /api/strategies/{S1}` is called
- THEN the request is refused before handler logic executes

### Requirement: The Share Preview Route Serves The Amount A Share Asks For

> **Added 2026-10-06 (owner decision 48, answered 2026-10-06; design addendum "unit 12f" § C2 and § H).**

`GET /api/strategies/{id}/share-preview`, with an optional query parameter `share`
(a decimal above 0 and at most 100 with at most 18 decimal places; default, the
strategy's stored share), MUST
answer 200 with:

- `strategy_id` (a UUID string);
- `pool`: `{exchange, venue, settlement_currency}`, the strategy's own pool,
  taken from the strategy named by the path and never from the request;
- `currency`: the pool's settlement currency;
- `pool_minimum`: the pool's own minimum order in that currency, as a string,
  never null;
- `balance`: `{total, observed_at, stale}` from the pool's latest balance
  snapshot, or null when the pool has none; `stale` follows the same rule as
  `GET /api/pools`;
- `exact`: `{share, amount, below_pool_minimum}` for the share asked, `share` a
  plain decimal string echoed in canonical form (no exponent, no trailing
  fractional zeros), or null when `balance` is null;
- `steps`: exactly 100 entries `{share, amount, below_pool_minimum}` for the
  whole shares 1 to 100 (`share` a JSON integer), or `[]` when `balance` is null.

An `amount` MUST be the pool's TOTAL balance (not what is free) times the share
divided by 100, computed by the function the allocation uses to size a request,
rounded down to 18 places, written as a string. `below_pool_minimum` MUST be true
exactly when the amount is below `pool_minimum`, the comparison the allocation
makes first. With no balance there MUST be no amount and never a zero. A stale
balance MUST still be served, marked. An archived strategy MUST be served.

It MUST answer 404 `{"detail": "no such strategy"}` for an unknown strategy, and
422, without echoing the rejected input, for a `share` that is not a decimal
above 0 and at most 100, or that is written with more than 18 decimal places. A strategy whose pool has no row MUST answer 500 and log
one ERROR naming the strategy and the pool. The route MUST require the bearer
token like every other `/api` route. The route MUST be read-only: it MUST read the
database only, MUST call no exchange, MUST open no stored credential and sign
nothing, MUST write nothing and MUST take no lock; the API process still decrypts
nothing. It MUST NOT check any pair's minimum order at the exchange.

#### Scenario: The stored share is previewed against the pool's balance

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` with a stored share of `33.5`, a pool minimum of 5 USDT and a snapshot total of 1000 USDT not stale
- WHEN `GET /api/strategies/{S1}/share-preview` is called
- THEN it answers 200 with `currency` `"USDT"`, `pool_minimum` `"5.000000000000000000"`, `balance.total` `"1000.000000000000000000"` with `stale` false, `exact` `{"share": "33.5", "amount": "335.000000000000000000", "below_pool_minimum": false}`, and 100 `steps`, the first `{"share": 1, "amount": "10.000000000000000000", "below_pool_minimum": false}` and the last `{"share": 100, "amount": "1000.000000000000000000", "below_pool_minimum": false}`

#### Scenario: A share asked for is served as exact

- GIVEN the same strategy and pool
- WHEN the route is called with `share=12.34`
- THEN `exact` is `{"share": "12.34", "amount": "123.400000000000000000", "below_pool_minimum": false}` and `steps` is still the 100 steps

#### Scenario: The exact share is echoed in canonical plain notation

- GIVEN the same strategy and pool
- WHEN the route is called with `share=33.50`
- THEN `exact.share` is `"33.5"`, with no trailing fractional zero and no exponent

#### Scenario: The amount is the allocation's own, rounded down

- GIVEN a snapshot total of 333.33 USDT and, in a second case, 10 USDT
- WHEN the route is called with `share=33.5` and with `share=33.333333333333333333` respectively
- THEN the amounts are `"111.665550000000000000"` and `"3.333333333333333333"`, each equal to what the allocation's sizing function returns for the same total and share

#### Scenario: The amount is of the total, not of what is free

- GIVEN pool `(bybit, usdt-m, USDT)` with a snapshot total of 1000 USDT and 400 USDT available
- WHEN the route is called with `share=10`
- THEN `exact.amount` is `"100.000000000000000000"`

#### Scenario: The minimum flag agrees with the allocation on both sides of the limit

- GIVEN pool `(bybit, usdt-m, USDT)` with a minimum of 5 USDT and snapshot totals of 499, 500 and 501 USDT in turn
- WHEN the route is called with `share=1` each time
- THEN `below_pool_minimum` is true for the amount 4.99, false for 5.00 and false for 5.01, and the allocation skips a request as below the pool's minimum for exactly the first

#### Scenario: A stale balance is still served, marked

- GIVEN the pool's latest snapshot is older than the staleness limit
- WHEN the route is called
- THEN it answers 200 with `balance.stale` true and the amounts

#### Scenario: A pool nothing has synced serves no amount

- GIVEN pool `(bybit, usdt-m, USDT)` has no balance snapshot
- WHEN the route is called
- THEN `balance` is null, `exact` is null, `steps` is `[]`, `pool_minimum` is still present, and no amount of zero is served

#### Scenario: An archived strategy is served

- GIVEN strategy S1 is archived with a stored share of `30`
- WHEN the route is called
- THEN it answers 200

#### Scenario: Each strategy answers its own pool

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` and strategy S2 on pool `(binance, usdt-m, USDT)`, with different balances
- WHEN each preview is read
- THEN each answers its own pool and its own total, and neither carries the other's

#### Scenario: An unknown strategy answers 404

- GIVEN no strategy under id X
- WHEN `GET /api/strategies/{X}/share-preview` is called
- THEN it answers 404 `{"detail": "no such strategy"}`

#### Scenario: A share outside the range is refused without echo

- GIVEN a valid bearer token
- WHEN the route is called with `share=0`, with `share=100.5` and with `share=abc`
- THEN each answers 422 and no body repeats the rejected value

#### Scenario: A strategy whose pool has no row is an integrity failure

- GIVEN strategy S1 names a pool with no stored row
- WHEN the route is called
- THEN it answers 500 and exactly one ERROR is logged naming S1 and the pool

#### Scenario: The route reads the database only

- GIVEN the route is called
- WHEN the exchange transports, the credential store and the locks are observed
- THEN no exchange was called, no stored credential was opened, nothing was signed, nothing was written and no lock was taken

#### Scenario: The route requires the bearer token

- GIVEN no bearer token is supplied
- WHEN `GET /api/strategies/{S1}/share-preview` is called
- THEN the request is refused before handler logic executes

### Requirement: A Share Has At Most 18 Decimal Places

> **Added 2026-10-09 (owner decision 50, answering a finding of task 12f.9.12; it replaces "with any number of decimals" in "The Strategy Update Takes The Share As A Plain Decimal And The Strategy View Serves It In Plain Notation").**

Every input of the admin API that takes a share of the pool MUST accept a value with
at most 18 decimal places, the scale this system uses for every amount, and MUST
refuse any other with the application's 422 that echoes no input. The inputs are the
`share` query of `GET /api/strategies/{id}/share-preview`, `allocation_percent` of
`PATCH /api/strategies/{id}` and `allocation_percent` of `POST /api/strategies`
(registration, which saves a share too). The places MUST be counted on the value as
written: trailing zeros count (`1.5000000000000000000` has 19) and an exponent is
read for what it writes (`1e-18` has 18, `1E+1` has none and is 10). The value MUST
NOT be normalised for the count, and the refusal MUST come before anything is
formatted, computed or stored, so that a value such as `1e-999999999` (which passes
the range of 0 to 100 in 12 characters, and written in plain notation is a text of
about 1 GB) is refused with a small body. A refused write MUST store nothing: the
stored share is unchanged (update) and no strategy exists (registration).

#### Scenario: Exactly 18 decimal places are accepted

- GIVEN strategy S1 with a stored share of `30`
- WHEN the update carries `0.123456789012345678`, or `1e-18`, and the preview is asked for the same shares
- THEN each answers success, the update stores the value, and `1e-18` is served as `0.000000000000000001`

#### Scenario: 19 decimal places are refused on the update

- GIVEN strategy S1 with a stored share of `30`
- WHEN the update carries `1e-19`, or `0.0000000000000000001`, or `1.5000000000000000000`
- THEN each answers 422, no body repeats the value, and the stored share is still `30`

#### Scenario: 19 decimal places are refused on the preview

- GIVEN strategy S1
- WHEN the preview is called with `share=1e-19`, or `share=1.5000000000000000000`
- THEN each answers 422 and no body repeats the value

#### Scenario: 19 decimal places are refused on the registration

- GIVEN no strategy under id X
- WHEN the registration of X carries `"allocation_percent": "1e-19"`
- THEN it answers 422, no body repeats the value, and no strategy X exists

#### Scenario: An exponent that is not a decimal place is still the value it writes

- GIVEN strategy S1
- WHEN the update carries `1E+1`
- THEN it answers 200 and the share is 10

#### Scenario: A value that would be a gigabyte is refused with a small body

- GIVEN strategy S1 with a stored share of `30`
- WHEN the preview, the update and the registration each carry `1e-999999999`
- THEN each answers 422 with a body of a few hundred bytes at most, the stored share is still `30`, and no strategy was registered

#### Scenario: A value past what the database can hold is refused, not a 500

- GIVEN strategy S1 with a stored share of `30`
- WHEN the update or the registration carries `1e-20000`
- THEN it answers 422 and nothing is stored

### Requirement: The Webhook's Origin Is Served By Its Own Route

> **Added 2026-10-06 (owner decisions 44 (12f.6) and 5; design addendum "unit 12f" § F).**

`GET /api/webhook-origin` MUST answer 200 `{"origin": "<origin>"}` or
`{"origin": null}`, requiring the same bearer token as every other `/api` route.
The origin MUST come from a setting (`WEBHOOK_PUBLIC_ORIGIN`), empty by default,
and MUST be the origin TradingView posts to, not the panel's. The body MUST NOT
contain the webhook secret. The setting MUST be read as an origin and nothing
more:

| Setting | Served |
| --- | --- |
| Empty | `null` |
| `https://example.org`, `http://localhost:8000` | as written |
| `HTTPS://Example.ORG`, `https://example.org/`, `https://example.org:443` | `https://example.org` (scheme and host in lower case, one trailing slash dropped, the scheme's default port dropped) |
| No scheme, a scheme other than `http` or `https`, an empty host | `null` |
| Anything after the authority: a path, a query, a fragment | `null` |
| A user or a password | `null` |
| A space, a control character, a backslash, a host with characters outside ASCII, a port that is not a number in range | `null` |

A malformed value MUST be served as `null`, MUST NOT stop the API from starting,
and MUST log one ERROR at startup naming the setting and the reason, never the
value. An empty setting MUST log one INFO at startup saying the panel shows the
path only. A well-formed value MUST log one INFO at startup with the normalised
origin. The raw value MUST NEVER be logged. The route MUST read a setting only:
no exchange is called, no credential opened and nothing signed; the API process
still decrypts nothing. Every value the route serves MUST be a serialised origin
(the panel accepts it).

#### Scenario: A configured origin is served

- GIVEN `WEBHOOK_PUBLIC_ORIGIN` is `https://example.duckdns.org`
- WHEN `GET /api/webhook-origin` is called with a valid bearer token
- THEN it answers 200 `{"origin": "https://example.duckdns.org"}`

#### Scenario: An unset setting serves null

- GIVEN `WEBHOOK_PUBLIC_ORIGIN` is empty
- WHEN the route is called
- THEN it answers 200 `{"origin": null}`, and exactly one INFO was logged at startup saying the panel shows the path only

#### Scenario: A local origin is accepted as written

- GIVEN `WEBHOOK_PUBLIC_ORIGIN` is `http://localhost:8000`
- WHEN the route is called
- THEN it answers `{"origin": "http://localhost:8000"}`

#### Scenario: Case, a trailing slash and the default port are normalised

- GIVEN `WEBHOOK_PUBLIC_ORIGIN` is, in turn, `HTTPS://Example.ORG`, `https://example.org/` and `https://example.org:443`
- WHEN the route is called each time
- THEN each answers `{"origin": "https://example.org"}`

#### Scenario: A value with a path, a query or a fragment is not served

- GIVEN `WEBHOOK_PUBLIC_ORIGIN` is, in turn, `https://example.org/hook`, `https://example.org?x=1` and `https://example.org#top`
- WHEN the route is called each time
- THEN each answers `{"origin": null}`

#### Scenario: A value with no scheme, another scheme or no host is not served

- GIVEN `WEBHOOK_PUBLIC_ORIGIN` is, in turn, `example.org`, `ftp://example.org` and `https://`
- WHEN the route is called each time
- THEN each answers `{"origin": null}`

#### Scenario: A value with a credential is not served and never logged

- GIVEN `WEBHOOK_PUBLIC_ORIGIN` is `https://user:pass@example.org`
- WHEN the API starts and the route is called
- THEN the route answers `{"origin": null}`, exactly one ERROR names the setting and the reason, and no log record contains `user:pass` or the raw value

#### Scenario: An unusable character or port is not served

- GIVEN `WEBHOOK_PUBLIC_ORIGIN` is, in turn, `https://exa mple.org`, `https://example.org\x`, `https://exämple.org` and `https://example.org:99999`
- WHEN the route is called each time
- THEN each answers `{"origin": null}`

#### Scenario: A malformed value does not stop the API

- GIVEN `WEBHOOK_PUBLIC_ORIGIN` is malformed
- WHEN the API starts
- THEN it starts, the webhook route is served, and the one ERROR is logged

#### Scenario: A well-formed value is logged normalised

- GIVEN `WEBHOOK_PUBLIC_ORIGIN` is `HTTPS://Example.ORG`
- WHEN the API starts
- THEN one INFO prints `https://example.org`

#### Scenario: The route never carries the secret

- GIVEN the configured webhook secret has a known value
- WHEN `GET /api/webhook-origin` is answered
- THEN the body does not contain it

#### Scenario: The route requires the bearer token

- GIVEN no bearer token, and in a second case a wrong one
- WHEN `GET /api/webhook-origin` is called
- THEN the request is refused before handler logic executes

### Requirement: The Strategy Performance Route Serves Each Pair's Wins And Win Rate

> **Added 2026-10-06 (owner decision 44, answered 2026-10-06; design addendum "unit 12f" § G).**

Each `by_pair` entry of the body of `GET /api/performance/strategies/{id}` MUST
carry two new fields, with nothing removed or renamed: `wins`, an integer with
0 <= `wins` <= `trades`, and `win_rate`, a string in the ratio notation of the
route's other ratios (10 decimal places), never null. `pair`, `trades`, `pnl` and
`return` MUST be unchanged. `win_rate` MUST be `wins` over `trades` as defined by
"A Pair's Win Rate Counts Closed Operations With A PnL Above Zero". The strategy
report's own figures and the pool report MUST NOT gain a win rate in this unit.
The route's authentication is unchanged.

#### Scenario: A pair carries its wins and its rate

- GIVEN strategy S1 on pool `(bybit, usdt-m, USDT)` has 5 closed live operations on `SOLUSDT`: 3 with a PnL above zero, 1 at exactly zero and 1 below zero
- WHEN `GET /api/performance/strategies/{S1}` is called
- THEN the `by_pair` entry for `SOLUSDT` carries `"trades": 5`, `"wins": 3` and `"win_rate": "0.6000000000"`, and still carries `pair`, `pnl` and `return`

#### Scenario: A pair with no win has a zero rate, not a null

- GIVEN strategy S1 has 3 closed operations on `ETHUSDT`, each with a PnL below zero
- WHEN the route is called
- THEN `ETHUSDT` carries `"wins": 0` and `"win_rate": "0.0000000000"`

#### Scenario: A pair that won every operation has a rate of 1

- GIVEN strategy S1 has 4 closed operations on `ETHUSDT`, each with a PnL above zero
- WHEN the route is called
- THEN `ETHUSDT` carries `"wins": 4` and `"win_rate": "1.0000000000"`

#### Scenario: No pair row is served for a pair with no closed operation

- GIVEN strategy S1 has no closed operation on `XRPUSDT`
- WHEN the route is called
- THEN no `by_pair` entry names `XRPUSDT`

#### Scenario: The strategy and pool reports gain no win rate

- GIVEN the route and the pool performance read are called
- WHEN their bodies are read outside `by_pair`
- THEN neither carries `wins` or `win_rate`
