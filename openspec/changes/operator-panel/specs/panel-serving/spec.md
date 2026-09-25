# Panel Serving Specification

## Purpose

FastAPI serves the built operator-panel SPA same-origin, alongside the
existing admin API, webhook, and health endpoints. Serving a client-side
route never shadows a reserved server path.

## Requirements

### Requirement: Static Assets Served Same-Origin

The system MUST serve the SPA's built static assets from the same FastAPI
process and origin that serves the admin API.

#### Scenario: Built assets are reachable

- GIVEN the SPA has been built and its assets mounted
- WHEN a GET request is made for a built asset path
- THEN the asset is served by the same FastAPI process serving `/api`

### Requirement: Clean-Route Fallback For Unmatched GETs

A GET request for a path that does not match `/api`, `/webhook/tradingview`,
`/health`, or a static asset path MUST be served `index.html`, so client-side
routes such as `/strategies/<uuid>` and `/settings` resolve on a direct
load or refresh.

#### Scenario: A deep client route resolves on direct load

- GIVEN the SPA defines a client-side route for `/strategies/<uuid>`
- WHEN `GET /strategies/<uuid>` is requested directly (not via client-side navigation)
- THEN the server responds with `index.html`

#### Scenario: The settings route resolves on refresh

- GIVEN the SPA defines a client-side route for `/settings`
- WHEN the browser is refreshed at `/settings`
- THEN the server responds with `index.html`

### Requirement: Reserved Paths Are Never Shadowed By the Fallback

The SPA fallback MUST NEVER intercept `/api/*`, `/webhook/tradingview`, or
`/health`. These three MUST always be matched by their own routes before the
fallback is considered, regardless of what client-side routes the SPA
defines.

#### Scenario: The fallback never serves index.html for /api

- GIVEN any path under `/api`
- WHEN a GET request is made to it
- THEN the response is never `index.html`, even if no matching `/api` route exists

#### Scenario: The fallback never intercepts the webhook

- GIVEN `POST /webhook/tradingview`
- WHEN the request is made
- THEN it is handled by the webhook route, never the SPA fallback

#### Scenario: The fallback never intercepts health

- GIVEN `GET /health`
- WHEN the request is made
- THEN it is handled by the health route, never the SPA fallback

### Requirement: Unknown API Path Returns 404 JSON, Never index.html

A request to a path under `/api` that does not match any registered admin
route MUST return a 404 JSON response. It MUST NEVER fall through to the SPA
fallback and return `index.html`.

#### Scenario: An unregistered /api path returns 404 JSON

- GIVEN no route is registered for `/api/unknown`
- WHEN `GET /api/unknown` is requested
- THEN the response is 404 with a JSON body, not `index.html`
