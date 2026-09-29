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
