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
