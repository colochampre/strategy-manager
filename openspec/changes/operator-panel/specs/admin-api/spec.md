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
>
> **Revised 2026-10-12 (owner decision 65, design addendum "open positions, a
> mark and a list read from the ledger" §§ B to G).** A new read, `GET
> /api/positions/open`, serves every open position and every order in flight of
> the whole system, built on the mode guard's own reader. Ten requirements
> are added after "The API Process Writes Its Own Log Lines"; no existing
> requirement of this file is changed. The route is covered by "Every Admin
> Route Is Mounted Under /api" and "Every Admin Route Requires the Bearer
> Token" as written. It adds no migration and changes no guard file. Four
> owner questions of that addendum (Q6 to Q9) concern the panel only, so none
> of them is marked in this file.

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

### Requirement: The API Process Writes Its Own Log Lines

> **Added 2026-10-09 (found by the deploy of PR 12f-1; tasks.md unit alg).**

The API process MUST write its own INFO, WARNING and ERROR lines to its
standard streams, whether operator alerting is on or off, each line once, in the
format the worker uses (`%(asctime)s %(levelname)-8s %(name)s: %(message)s`).
It MUST do so by giving the root logger the level INFO and a handler of its own,
installed before anything else in the API's startup can log and before the
operator-alert bridge is installed. It MUST recognise its own handler, so that
configuring twice, or configuring while another handler is already on the root
logger (a test runner's capture, the alert bridge), writes each line once and
never zero times.

This MUST NOT change what the process already writes elsewhere: uvicorn's access
and error lines MUST still be written once each, and the access line MUST still
mask the webhook's secret. The INFO lines of `httpx` and `httpcore` MUST NOT be
written, because the Telegram URL holds the bot token and a Binance URL its
signature; their WARNING lines MUST be.

#### Scenario: An INFO line is written

- GIVEN the API is running under uvicorn's default logging configuration
- WHEN an application logger writes an INFO
- THEN the line is written once to a standard stream, in the worker's format

#### Scenario: A WARNING and an ERROR are written while alerting is on

- GIVEN a handler that writes nowhere is on the root logger, as the alert bridge is
- WHEN an application logger writes an INFO, a WARNING and an ERROR
- THEN each is written once to a standard stream

#### Scenario: A handler installed first does not stop the configuration

- GIVEN another handler was already on the root logger when the API configured its logging
- WHEN an application logger writes an INFO, a WARNING and an ERROR
- THEN each is written once to a standard stream

#### Scenario: The origin's startup line reaches the journal

- GIVEN `WEBHOOK_PUBLIC_ORIGIN` is `https://hook.example.org`
- WHEN the API starts
- THEN exactly one line naming `WEBHOOK_PUBLIC_ORIGIN` and `https://hook.example.org` is written to a standard stream

#### Scenario: Configuring twice writes each line once

- GIVEN the API's logging was configured twice
- WHEN an application logger writes a line
- THEN it is written once

#### Scenario: Uvicorn's lines are not doubled and the secret stays masked

- GIVEN the API's logging is configured
- WHEN uvicorn writes an access line for `/webhook/tradingview?secret=hunter2` and an error-logger line
- THEN each is written once, and the access line shows `secret=REDACTED` and no output holds `hunter2`

#### Scenario: The HTTP client's INFO lines stay out

- GIVEN the API's logging is configured
- WHEN `httpx` and `httpcore` each write an INFO and a WARNING
- THEN neither INFO is written and each WARNING is written once

#### Scenario: Logging is configured before the alert bridge

- GIVEN the API starts
- WHEN `operator_alerts` is about to install its bridge
- THEN the root logger is already at INFO and holds the API's own handler

### Requirement: The Open Positions Route Answers For The Whole System

> **Added 2026-10-12 (owner decision 65; design addendum "open positions" § F).**

`GET /api/positions/open` MUST answer 200 with a body of exactly three fields:
`as_of` (the server's clock when the snapshot was read, a UTC instant),
`positions` (one element per open allocation) and `orders` (one element per
order in flight). It MUST take no path parameter and no query parameter and
MUST answer for the WHOLE system: every pool, enabled or not, and every
strategy, archived or not. It MUST NOT filter by exchange, by strategy or by
pool. It MUST require the bearer token of every `/api` route. Money,
quantities and the leverage MUST be JSON strings in plain notation, prices MUST
be rounded to 18 places, and instants MUST be UTC, as `wire.py` writes them.

`positions` MUST be sorted by strategy name, pool, market and allocation id;
`orders` by the instant they were sent and attempt id. Each element MUST carry
its own pool (`exchange`, `venue`, `settlement_currency`, three non-empty
strings, always) and its own currency. The body MUST carry no count and no
total, and no field MUST add the money of two positions (rules 5 and 7). The
route has no subject, so it MUST NOT answer 404. A failure of the read MUST
answer 500, never an empty list.

#### Scenario: The route serves the three fields

- GIVEN an empty ledger and no attempt in flight
- WHEN `GET /api/positions/open` is called with a valid bearer token
- THEN it answers 200 with `positions` and `orders` both empty lists and an `as_of` instant in UTC, and no other field

#### Scenario: Two pools of two exchanges are served in one answer, each with its own pool

- GIVEN an open position in pool `(bybit, usdt-m, USDT)` and another in pool `(binance, usdt-m, USDT)`
- WHEN the route is called
- THEN `positions` holds both, each with its own `pool` and `currency`, and the body holds no count, no total and no field that adds the two

#### Scenario: No parameter narrows the answer

- GIVEN open positions on two exchanges
- WHEN the route is called with `?exchange=bybit`, and again without it
- THEN both answers hold the positions of both exchanges

#### Scenario: A disabled pool and an archived strategy are served

- GIVEN an open position of an archived strategy in a pool that is disabled
- WHEN the route is called
- THEN the position is in `positions`

#### Scenario: Positions and orders are sorted

- GIVEN positions of strategies "B" and "A", and two positions of "A" on `SOLUSDT` and `AAVEUSDT`, and two orders sent at different times
- WHEN the route is called
- THEN `positions` lists "A" before "B", "A"'s `AAVEUSDT` before its `SOLUSDT`, and `orders` lists the earlier-sent first

#### Scenario: Plain notation and UTC

- GIVEN a position with a leverage stored as `2.00000000` and a fee of `0.00000001`
- WHEN the route is called
- THEN the leverage and the fee are JSON strings without an exponent, every price has at most 18 decimal places, and every instant carries a UTC offset

#### Scenario: The route requires the bearer token

- GIVEN no bearer token, and in a second case a wrong one
- WHEN `GET /api/positions/open` is called
- THEN the request is refused before handler logic executes

#### Scenario: A failed read is an error, never an empty list

- GIVEN a database failure while the route reads
- WHEN the route is called
- THEN it answers 500 and not 200 with empty lists, and no 404 is ever answered by this route

### Requirement: An Empty Answer Means The Mode Guard's Two Inputs Were Empty

> **Added 2026-10-12 (owner decision 65; design addendum "open positions" § B, the invariant).**

The route MUST be built on the mode guard's own reader
(`SqlAlchemyModeOriginReader`): the same class, the same statements and the
same domain fold that decide whether the worker may start. It MUST emit exactly
one element per element of the reader's open allocations (kind position) and
one per element of its in-flight attempts (kind order), unconditionally. The
figures, the margin, the leverage and the venue mark only decorate an element
and MUST NEVER remove one. No branch of the route MAY filter, group or merge
the two sequences. The answer MUST NOT depend on `DRY_RUN`.

The invariant: when the answer has an empty `positions` and an empty `orders`,
then on the same database state `assert_mode_matches_ledger` MUST raise for
neither value of `DRY_RUN`.

| What the tables hold | Guard, `DRY_RUN=false` | Guard, `DRY_RUN=true` | The route |
| --- | --- | --- | --- |
| Open allocation, rehearsal fills only | refuses | starts | a position, origin `rehearsal` |
| Open allocation, live fills only | starts | refuses | a position, origin `live` |
| Open allocation holding fills of both | refuses | refuses | a position, origin `mixed` |
| Allocation with a symbol that cannot be split, any net | as its fills' origin says | as its fills' origin says | a position, figures absent with the reason |
| Allocation whose net is exactly zero | not seen | not seen | not served |
| `SUBMITTED` attempt, order id `fake-order-...` | refuses | starts | an order, origin `rehearsal` |
| `SUBMITTED` attempt, any other order id | starts | refuses | an order, origin `live` |
| `SUBMITTED` attempt, order id NULL | not seen | not seen | an order, origin `unknown` |
| A reservation with no attempt yet | not seen | not seen | not served |

#### Scenario: Each case of the table is served as the table says

- GIVEN one database state holding one case of each row of the table
- WHEN the route is called
- THEN `positions` and `orders` hold exactly the elements the last column names, and none for the rows that say "not served"

#### Scenario: The positions are the reader's open allocations, one for one

- GIVEN a database state with three open allocations, two of which share a strategy
- WHEN the route is called and, on the same state, the guard's reader is asked for its open allocations
- THEN `positions` has the same allocation ids, no more and no fewer

#### Scenario: The orders are the reader's in-flight attempts, plus the ones it cannot judge

- GIVEN two `SUBMITTED` attempts with an order id and one with a NULL order id
- WHEN the route is called
- THEN `orders` holds all three, and the one with no order id has origin `unknown`

#### Scenario: An empty answer is a state the guard accepts in both modes

- GIVEN the route answers empty lists
- WHEN `assert_mode_matches_ledger` is run on the same state for `DRY_RUN=true` and for `DRY_RUN=false`
- THEN it raises for neither

#### Scenario: A rehearsal position is served in either mode

- GIVEN an open allocation filled by the simulated exchange
- WHEN the route is called with `DRY_RUN=true`, and again with `DRY_RUN=false`
- THEN the position is in both answers, with origin `rehearsal`

#### Scenario: A live fill id that only contains the rehearsal marker is live

- GIVEN an open allocation whose fill id contains `fake-fill-` but does not start with it
- WHEN the route is called
- THEN its origin is `live`, the same origin the guard gives it

#### Scenario: A position that decoration cannot reach is still served

- GIVEN the facts read answers nothing for an allocation the guard's reader returned
- WHEN the route is called
- THEN the allocation is in `positions` (see "A Position Or An Order The Facts Cannot Decorate Keeps Its Row")

### Requirement: A Position Element Carries Its Identity, Its Pool, Its Origin And Its Figures

> **Added 2026-10-12 (owner decision 65; design addendum "open positions" §§ D and F).**

Each element of `positions` MUST carry these fields, and no other:

| Field | Value |
| --- | --- |
| `allocation_id` | the position's identity |
| `strategy_id` | the reservation's strategy, or null only for a position the facts cannot decorate |
| `strategy_name` | never null |
| `strategy_archived` | boolean, or null only with `strategy_id` null |
| `pool` | the pool of the allocation's fills, as the guard labels it |
| `currency` | the pool's settlement currency, the unit of `entry_price`, `fees` and `margin_granted` |
| `markets` | market keys, sorted, one market written once |
| `origin` | `"rehearsal"`, `"live"` or `"mixed"` |
| `figures_missing` | a reason or null |
| `side` | `"LONG"`, `"SHORT"` or null |
| `base_currency`, `size`, `opened_size`, `entry_price` | the figures, or null |
| `opened_at` | the earliest fill instant, or null only for a position the facts cannot decorate |
| `fill_count` | the number of ledger rows of the allocation |
| `fees`, `other_fees` | the fees paid so far |
| `margin_granted` | the reservation's amount, as stored |
| `leverage` | the opening order's leverage, as stored, or null |
| `reservation_status` | the reservation's status as stored, or null only for a position the facts cannot decorate |
| `venue_disagreement` | an object or null |

The route MUST NOT serve a position's last fill time, the kind of a
discrepancy, the instant it was first confirmed, or an order's allocation id,
side or margin reserved. A position MUST be identified and grouped by its
allocation id and never by symbol. A position's `markets` MUST be market keys:
one market opened as `STXUSDT.P` and booked as `STXUSDT` MUST read
`["STXUSDT"]`. The route MUST NOT convert any amount to another currency.

#### Scenario: A live futures position carries every field

- GIVEN allocation A1 of strategy S1 in pool `(bybit, usdt-m, USDT)`, opened by one live fill of 0.5 SOL on `SOLUSDT` at 100, reserved at 20 with an opening order at leverage 3
- WHEN the route is called
- THEN the element carries `allocation_id` A1, `strategy_id` S1, the strategy's name, `strategy_archived` false, the pool, `currency` `USDT`, `markets` `["SOLUSDT"]`, `origin` `live`, `figures_missing` null, `side` `LONG`, `base_currency` `SOL`, `size` `0.5`, `opened_size` `0.5`, `entry_price` `100`, `fill_count` 1, `margin_granted` `20`, `leverage` `3`, `reservation_status` `FILLED` and `venue_disagreement` null

#### Scenario: One market under two spellings is one market

- GIVEN an allocation opened as `STXUSDT.P` and booked as `STXUSDT`
- WHEN the route is called
- THEN `markets` is `["STXUSDT"]` and there is one element

#### Scenario: A position is identified by its allocation, not by its symbol

- GIVEN strategy S1 holds allocation A1 and strategy S2 holds allocation A2, both on `SOLUSDT` in one pool
- WHEN the route is called
- THEN `positions` holds two elements, one per allocation id

#### Scenario: Every pool is a label of the element

- GIVEN a position whose fills name pool `(bybit, usdt-m, USDT)`
- WHEN the route is called
- THEN its `pool` is that pool, with three non-empty strings, and `currency` is `USDT`

#### Scenario: The six unread fields are not served

- GIVEN any open position and any order in flight
- WHEN the route is called
- THEN no element carries a position's last fill time, the discrepancy's kind or first-confirmed instant, or an order's allocation id, side or margin reserved

#### Scenario: A position of an archived strategy says so

- GIVEN an open position of an archived strategy
- WHEN the route is called
- THEN its `strategy_archived` is true

#### Scenario: A reservation that is not FILLED is served as stored

- GIVEN an open allocation whose reservation status is `EXPIRED`
- WHEN the route is called
- THEN `reservation_status` is `EXPIRED`, the element is in `positions`, and one WARNING names the allocation id

### Requirement: The Figures Of A Position Are Derived From Its Fills, And Are Absent Together Or Not At All

> **Added 2026-10-12 (owner decision 65; design addendum "open positions" § D).**

The five figures `side`, `base_currency`, `size`, `opened_size` and
`entry_price` MUST be derived together from the fills of ONE allocation, or be
null together with `figures_missing` naming the reason. The net is the base
quantity bought, minus the base quantity sold, minus every fee charged in the
base currency; it is the arithmetic of the guard's fold, written for display.

- `side` is `LONG` when the net is above zero and `SHORT` when below.
- `size` is the absolute net, in the base currency; `opened_size` is the sum of
  the quantities of the held side (BUY for a LONG, SELL for a SHORT).
- `entry_price` is the quantity-weighted average of the held side's fills
  (sum of notional over sum of quantity), in the settlement currency per unit
  of base. A close does not change what the position was opened at.
- `fees` is the sum of every fill's fee charged in the settlement currency, both
  sides, as the closed operations count it; a fee in any other currency MUST be
  listed in `other_fees` as `{currency, amount}`, one per currency whose sum is
  above zero, and MUST NOT be converted. A fee in the base currency is listed
  there and is already inside `size`.
- `margin_granted` MUST be the reservation's amount as stored, never recomputed
  and never compared with the venue. `leverage` MUST be the opening attempt's
  leverage as stored: null for a spot order or where none was recorded, never
  defaulted. A rehearsal position reads 1 because the simulated exchange
  records 1.
- A position opened by several fills is ONE element; `opened_at` is the first
  fill's instant.

`figures_missing` MUST be one of: `UNRESOLVED_SYMBOL` (the base currency cannot
be told from the pool's currency), `SEVERAL_MARKETS` (the fills name more than
one market key), `FLIPPED` (the net's sign is the opposite of the earliest
fill's side), `INCONSISTENT` (the net computed here is zero, or the held side
has no quantity or notional above zero) or `NO_FACTS` (see the next
requirement). With any reason other than `NO_FACTS` the element MUST still
carry its markets, origin, `opened_at`, `fill_count`, `fees`, `other_fees`,
`margin_granted` and `leverage`. The derivation MUST NOT raise for a row.

#### Scenario: A long position from one fill

- GIVEN one BUY fill of 0.5 SOL at 100 with a fee of 0.02 USDT, in a USDT pool
- WHEN the route is called
- THEN `side` is `LONG`, `size` and `opened_size` are `0.5`, `entry_price` is `100`, `fees` is `0.02` and `other_fees` is empty

#### Scenario: A short position

- GIVEN one SELL fill of 0.3 AAVE at 200 and nothing else
- WHEN the route is called
- THEN `side` is `SHORT`, `size` and `opened_size` are `0.3` and `entry_price` is `200`

#### Scenario: Several fills average, and the position is one element

- GIVEN three BUY fills of 0.1 at 100, 0.1 at 110 and 0.3 at 120
- WHEN the route is called
- THEN there is one element with `fill_count` 3, `opened_size` `0.5`, `entry_price` `114` and `opened_at` the earliest fill's instant

#### Scenario: A position closed in part keeps what it was opened at

- GIVEN a BUY of 0.5 AAVE at 100 and a SELL of 0.2 AAVE at 120
- WHEN the route is called
- THEN `size` is `0.3`, `opened_size` is `0.5`, `entry_price` is `100`, and `fees` includes the SELL's fee

#### Scenario: A fee in the base currency shrinks the size and is listed apart

- GIVEN a BUY of 1 SOL whose fee of 0.001 was charged in SOL, in a USDT pool
- WHEN the route is called
- THEN `size` is `0.999`, `opened_size` is `1`, `fees` does not include it, and `other_fees` holds `{currency: "SOL", amount: "0.001"}`

#### Scenario: The margin is the reservation's amount, not recomputed

- GIVEN a reservation of 20 USDT and an opening order at leverage 3 that filled 0.5 SOL at 100
- WHEN the route is called
- THEN `margin_granted` is `20`, not 50 and not the fill's notional

#### Scenario: A spot order has no leverage, and a rehearsal one has 1

- GIVEN one open spot allocation whose opening attempt has no leverage, and one rehearsal allocation whose opening attempt recorded 1
- WHEN the route is called
- THEN the first element's `leverage` is null and the second's is `1`

#### Scenario: A symbol that cannot be split keeps the row and says why

- GIVEN an allocation on `XYZBTC` in a USDT pool, with a net other than zero
- WHEN the route is called
- THEN the element is served with `figures_missing` `UNRESOLVED_SYMBOL`, `side`, `base_currency`, `size`, `opened_size` and `entry_price` null, and `markets`, `origin`, `opened_at`, `fees`, `margin_granted` and `leverage` present, and one WARNING names the allocation id

#### Scenario: Fills that name two markets keep the row

- GIVEN an allocation whose fills name `SOLUSDT` and `AAVEUSDT`
- WHEN the route is called
- THEN `figures_missing` is `SEVERAL_MARKETS` and `markets` holds both

#### Scenario: A net that flipped has no entry price

- GIVEN an allocation whose first fill is a BUY and whose net is below zero
- WHEN the route is called
- THEN `figures_missing` is `FLIPPED` and the five figures are null

#### Scenario: A net of zero where the fold says open

- GIVEN a state in which the net computed for display is zero while the fold counts the allocation open
- WHEN the route is called
- THEN the element is served with `figures_missing` `INCONSISTENT`, never dropped and never with a size of 0, and one WARNING names the allocation id

### Requirement: A Position Or An Order The Facts Cannot Decorate Keeps Its Row

> **Added 2026-10-12 (owner decision 65; design addendum "open positions" § C and § F).**

When the facts read answers nothing for an allocation the guard's reader
returned, the element MUST be built from the reader's own element with
`figures_missing` `NO_FACTS`: `strategy_name`, `pool`, `markets` and `origin`
present; `strategy_id`, `strategy_archived`, `opened_at`, `fees`,
`margin_granted`, `leverage` and `reservation_status` null (never a zero, since
a zero fee would say the position paid none); `fill_count` 0; `other_fees` an
empty list. Its `markets` MUST be market keys: the reader joins the raw
spellings with ` / `, so the route MUST split on that separator, normalise each
piece, drop duplicates and sort.

When an order the reader returned has no row in the submitted-orders read, the
order MUST be served from the reader's element with `strategy_id`,
`strategy_archived`, `action` and `submitted_at` null. An order's `market` MUST
be the market key of its symbol from either source. Each such element MUST log
one WARNING with its id on every read, and no price, quantity, fee or margin.

#### Scenario: A position with no facts is served with nulls

- GIVEN the facts read answers nothing for allocation A1
- WHEN the route is called
- THEN A1's element has `figures_missing` `NO_FACTS`, `strategy_id`, `strategy_archived`, `opened_at`, `fees`, `margin_granted`, `leverage` and `reservation_status` null, `fill_count` 0 and `other_fees` `[]`, and its name, pool, markets and origin are present

#### Scenario: Its markets are normalised

- GIVEN the reader's element for A1 reads `STXUSDT / STXUSDT.P`
- WHEN the route is called
- THEN `markets` is `["STXUSDT"]`

#### Scenario: An undecorated order keeps its row

- GIVEN the submitted-orders read has no row for an attempt the reader returned
- WHEN the route is called
- THEN the order is in `orders` with `strategy_id`, `strategy_archived`, `action` and `submitted_at` null, and its pool, market and origin present

#### Scenario: Each such element logs one WARNING with its id

- GIVEN one position with no facts and one undecorated order
- WHEN the route is called
- THEN one WARNING names the allocation id and one names the attempt id, and no log record contains a price, quantity, fee or margin

### Requirement: An Order In Flight Is Served With Its Origin, Including An Unknown One

> **Added 2026-10-12 (owner decision 65; design addendum "open positions" §§ B, C and F).**

Each element of `orders` MUST carry `attempt_id`, `strategy_id`,
`strategy_archived`, `strategy_name`, `pool` (the attempt's own pool columns,
three non-empty strings), `market` (the market key of its symbol), `action`,
`origin` and `submitted_at`. `action` MUST be `OPEN` when the attempt belongs to
a reservation and `CLOSE` when it closes an allocation, or null on an order the
facts could not decorate. `origin` MUST be `rehearsal` for an order id with the
simulated exchange's prefix, `live` for any other order id, and `unknown` when
no order id is recorded. `submitted_at` MUST be the attempt's creation instant,
so that an order in flight for hours is visible as such. An attempt that is
not `SUBMITTED` MUST NOT be served. An attempt with no order id is a normal
short state, since the id is written after the order is sent, and a lasting one
after a crash in between.

#### Scenario: An opening order with a live order id

- GIVEN a `SUBMITTED` opening attempt with order id `1234567`
- WHEN the route is called
- THEN the order has `action` `OPEN`, `origin` `live` and `submitted_at` the attempt's creation instant

#### Scenario: A closing order with a rehearsal order id

- GIVEN a `SUBMITTED` closing attempt with order id `fake-order-9`
- WHEN the route is called
- THEN the order has `action` `CLOSE` and `origin` `rehearsal`

#### Scenario: An order with no order id is unknown

- GIVEN a `SUBMITTED` attempt whose order id is NULL
- WHEN the route is called
- THEN the order is served with `origin` `unknown`

#### Scenario: A filled attempt is not an order in flight

- GIVEN an attempt whose status is `FILLED`
- WHEN the route is called
- THEN it is not in `orders`

#### Scenario: The market is a market key

- GIVEN a `SUBMITTED` attempt on the symbol `STXUSDT.P`
- WHEN the route is called
- THEN the order's `market` is `STXUSDT`

### Requirement: A Position The Venue Disagrees On Carries The Reconciliation's Finding

> **Added 2026-10-12 (owner decision 65, 2026-10-11 fourth question; design addendum "open positions" § E).**

A position's `venue_disagreement` MUST be non-null exactly when an open
`CONFIRMED` row of `reconciliation_discrepancies`, of THE POSITION'S POOL, lists
THE POSITION'S ALLOCATION ID among its open allocation ids; the market is not
the key. When set it MUST carry `discrepancy_id`, `venue_net_base`,
`ledger_net_base`, `allocation_count` (the number of allocations the row lists)
and `last_observed_at`. A row that is only `OBSERVED`, a resolved row, a row of
another pool, and a row that lists no allocation of the position MUST mark
nothing. When two or more positions share the pair, every one of them MUST
carry the mark, and `allocation_count` MUST say so. A confirmed disagreement on
a market the ledger holds nothing on has no position to mark and MUST NOT
create an element. The mark MUST use what the reconciliation already found: the
route MUST NOT read any venue and MUST NOT write.

#### Scenario: A confirmed row names the allocation

- GIVEN an open `CONFIRMED` discrepancy in the position's pool listing A1, with venue net `0` and ledger net `0.82`
- WHEN the route is called
- THEN A1's `venue_disagreement` carries that discrepancy's id, venue net `0`, ledger net `0.82`, `allocation_count` 1 and its `last_observed_at`

#### Scenario: An observed row marks nothing

- GIVEN a discrepancy that is `OBSERVED` and lists A1
- WHEN the route is called
- THEN A1's `venue_disagreement` is null

#### Scenario: A resolved row marks nothing

- GIVEN a `CONFIRMED` discrepancy listing A1 whose `resolved_at` is set
- WHEN the route is called
- THEN A1's `venue_disagreement` is null

#### Scenario: A stale row cannot mark a later position on the same market

- GIVEN an open `CONFIRMED` row for `SOLUSDT` that lists allocation A0, which is no longer open, and a new rehearsal allocation A1 on `SOLUSDT`
- WHEN the route is called
- THEN A1's `venue_disagreement` is null

#### Scenario: A row of another pool marks nothing

- GIVEN an open `CONFIRMED` row of pool `(binance, usdt-m, USDT)` listing A1, whose pool is `(bybit, usdt-m, USDT)`
- WHEN the route is called
- THEN A1's `venue_disagreement` is null

#### Scenario: Two positions on one pair share the mark

- GIVEN an open `CONFIRMED` row listing A1 and A2, two allocations open on `AAVEUSDT` in one pool
- WHEN the route is called
- THEN both elements carry the mark, each with `allocation_count` 2

#### Scenario: A confirmed row on a market the ledger holds nothing on adds no element

- GIVEN an open `CONFIRMED` row of kind "no matching allocation" and no open allocation in that pool
- WHEN the route is called
- THEN `positions` is empty

#### Scenario: The mark reads no venue

- GIVEN a venue client that fails the test if it is called
- WHEN the route is called with a confirmed row present
- THEN the client is never called and no row of any table is written

### Requirement: A Difference Between Pools Is Logged And Never Changes The Answer

> **Added 2026-10-12 (owner decision 65; design addendum "open positions" § C, the check added on 2026-10-12, and § K rows 4, 9 to 12 and 16 to 17).**

An element's `pool` is the guard's own label; it decides which exchange tab
shows the element, so a wrong one hides it. The route MUST therefore compare it
with the reservation's pool, and for a position it MUST compare EVERY group of
its fills with two things: the element's own pool and the reservation's pool (a
group naming another pool is a difference), and the reservation's strategy (a
group whose fills belong to another strategy is a difference). An order has one
attempt and one reservation, so its pools are compared; a `SUBMITTED` attempt
that joins to no reservation is a difference too. The route MUST log ONE
WARNING per allocation or attempt with a difference, naming its id and the pools
(and, for a position, the strategy ids) found, and nothing else. It MUST change
NOTHING in the answer: the row stays, its `pool` stays the guard's element's and
its `strategy_id` stays the reservation's. The log level MUST be WARNING, never
ERROR, and no price, quantity, fee or margin MAY be logged. The WARNINGs repeat
on every read while the fault exists.

#### Scenario: An allocation whose fills name another pool than its reservation

- GIVEN allocation A1 whose reservation is in pool `(bybit, usdt-m, USDT)` and whose fills name `(binance, usdt-m, USDT)`
- WHEN the route is called
- THEN A1 is served with the pool the guard labels it with, and one WARNING names A1 and both pools

#### Scenario: Fills of an allocation name two pools

- GIVEN allocation A1 with one group of fills in pool P1 and one in pool P2
- WHEN the route is called
- THEN one WARNING names A1 and both pools found, and the answer is the same as it would be without the check

#### Scenario: Fills that belong to another strategy

- GIVEN allocation A1 whose reservation belongs to S1 and one of whose groups of fills belongs to S2
- WHEN the route is called
- THEN one WARNING names A1 and both strategy ids, and the element's `strategy_id` is S1

#### Scenario: An order whose attempt names another pool than its reservation

- GIVEN a `SUBMITTED` attempt whose pool is not its reservation's
- WHEN the route is called
- THEN the order is served with the attempt's own pool and one WARNING names the attempt id and both pools

#### Scenario: A submitted attempt with no reservation at all

- GIVEN a `SUBMITTED` attempt with neither a reservation nor a closed allocation
- WHEN the route is called
- THEN the order is served and one WARNING names the attempt id

#### Scenario: Nothing is logged when nothing is wrong

- GIVEN every element's pool and strategy equal its reservation's, and every position has facts, a splittable symbol and a FILLED reservation
- WHEN the route is called
- THEN no WARNING is written by the read, and no ERROR is ever written by it

#### Scenario: The check repeats on every read

- GIVEN a standing difference
- WHEN the route is called twice
- THEN one WARNING is written per call

### Requirement: One Request Reads One Database State And Writes Nothing

> **Added 2026-10-12 (owner decision 65; design addendum "open positions" § G).**

All the statements of one request MUST see one database state, as of the first
read, inside a read-only transaction. The route MUST write nothing, MUST take no
advisory lock and no row lock, and MUST NOT delay a settle or an allocation.
The number of statements MUST NOT grow with the number of positions. Under
that snapshot the answer is the state of one instant, whole: an order is in
flight and its position is not yet there, or the position is there and the
order is gone; never both, never neither. The read MUST need no credential and MUST work
the same in both values of `DRY_RUN`.

#### Scenario: A fill committed during the read does not show two states

- GIVEN an order in flight whose fills and `FILLED` status are committed in one transaction while the route is reading
- WHEN the route is called
- THEN the answer holds the order and not its position, or the position and not its order, and never neither

#### Scenario: The route does not wait for the allocation lock

- GIVEN another transaction holds `pg_advisory_xact_lock` for the pool `(bybit, usdt-m, USDT)`
- WHEN the route is called
- THEN it answers without waiting for that transaction to end

#### Scenario: A settle is not delayed by the route

- GIVEN the route is mid-read
- WHEN a settle writes fills and the attempt's status
- THEN the settle completes without waiting for the route, and the route raises no serialization error

#### Scenario: The statement count does not grow with the positions

- GIVEN the same database with 1 open position and with 20
- WHEN the route is called on each
- THEN it issues the same number of statements

#### Scenario: A read writes no row

- GIVEN any database state
- WHEN the route is called
- THEN no table changes

#### Scenario: No credential is needed

- GIVEN `DRY_RUN=true` and no exchange credential in the vault
- WHEN the route is called
- THEN it answers 200

### Requirement: The Unit Changes No Guard File And Adds No Migration

> **Added 2026-10-12 (owner decision 65; design addendum "open positions" § B and § G).**

The route MUST add no migration and no table, column, constraint or trigger.
The mode guard (`mode_origin.py`, `mode_origin_reader.py`,
`assert_mode_matches_ledger.py` and `main.assert_dry_run_matches_ledger`) and
its four test files MUST be unchanged, so that its tests keep pinning it as they
do today. The only change to `main.py` MUST be the import of the new router and
its registration beside the other admin routers. The reader gains a second
caller and MUST read and write nothing more than for the first.

#### Scenario: The migration head is unchanged

- GIVEN the change is applied
- WHEN `alembic heads` is read
- THEN it names the same revision as before the change

#### Scenario: The guard's tests pass unchanged

- GIVEN the guard's domain tests, its reader's integration tests, its use case's tests and its wiring tests, with no line edited
- WHEN they run
- THEN they pass

#### Scenario: The diff touches none of the guard's files

- GIVEN the change's diff
- WHEN its file names are read
- THEN none is a guard source file or one of its four test files, and `main.py` changes only by the router's import and registration

#### Scenario: The reader's second caller changes nothing

- GIVEN the guard is run before and after the route is called
- WHEN the two guard results are compared
- THEN they are equal

### Requirement: The Confirmed Discrepancies Route Is An Admin Route Under /api

> **Added 2026-10-16 (owner decision 66; design addendum "PR 15" § G; the route's contract is in the `venue-reconciliation` delta, "Confirmed Discrepancy Read Endpoint").**

`GET /api/reconciliation/confirmed` MUST be mounted on the existing reconciliation router, so that "Every Admin Route Is Mounted Under /api" and "Every Admin Route Requires the Bearer Token" apply to it by the router's own mounting. It MUST take no parameter and MUST NOT write.

#### Scenario: The route is mounted under /api with the bearer

- GIVEN the application
- WHEN the route table is read
- THEN `/api/reconciliation/confirmed` is registered with the admin bearer dependency and no unprefixed twin exists

#### Scenario: Without the bearer it is refused

- GIVEN no bearer token
- WHEN the route is called
- THEN the answer is 401 before any handler logic

### Requirement: The Booking Routes Are Removed

> **Added 2026-10-16 (owner decision 66, Q1 answered (a); design addendum "PR 15" § F).**

`GET /api/reconciliation/bookings`, `POST /api/reconciliation/bookings/{id}/approve` and `POST /api/reconciliation/bookings/{id}/reject` MUST NOT exist. A request to any of them MUST be answered 404 or 405 and MUST reach no use case. `RejectBooking` and its route-only code MUST be removed; `ApproveBooking` MUST remain, called by the worker, and `GET /api/reconciliation/discrepancies` MUST remain unchanged.

#### Scenario: The list route is gone

- GIVEN a valid bearer
- WHEN `GET /api/reconciliation/bookings` is called
- THEN the answer is 404 or 405

#### Scenario: The approve route is gone

- GIVEN a valid bearer and an existing PENDING proposal
- WHEN `POST /api/reconciliation/bookings/{id}/approve` is called
- THEN the answer is 404 or 405 and the proposal is still PENDING

#### Scenario: The reject route is gone

- GIVEN a valid bearer and an existing PENDING proposal
- WHEN `POST /api/reconciliation/bookings/{id}/reject` is called
- THEN the answer is 404 or 405 and the proposal is still PENDING

#### Scenario: The approval use case is still called by the worker

- GIVEN the router module
- WHEN its imports are read
- THEN it imports neither `ApproveBooking` nor `RejectBooking`, and the worker's wiring still builds `ApproveBooking`

### Requirement: The Confirmed-Discrepancies Unit Adds No Migration And Changes No Guard File

> **Added 2026-10-16 (owner decision 66; design addendum "PR 15" § F and § J).**

The unit MUST add no migration and the Alembic head MUST be unchanged. No module outside `reconciliation` changes on the backend except `main.py`'s wiring and the two new settings, `reconciliation_auto_booking_grace_seconds` and `reconciliation_needs_owner_reminder_seconds`. The mode guard's files and tests MUST be unchanged.

#### Scenario: The migration head is unchanged

- GIVEN the change is applied
- WHEN `alembic heads` is read
- THEN it names the same revision as before the change

#### Scenario: The diff stays inside reconciliation, main.py and config

- GIVEN the unit's backend diff
- WHEN its file names are read
- THEN each is under `reconciliation/`, or is `main.py`, `shared/config.py` or a test
