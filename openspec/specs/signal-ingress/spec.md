# Signal Ingress Specification

## Purpose

Accept TradingView webhook signals, authenticate and persist them idempotently, and hand off to the job queue — without ever executing a trade inline. This module is the sole entry point for strategy signals.

## Requirements

### Requirement: Webhook Authentication

The system MUST authenticate every incoming webhook request by BOTH a shared secret AND the request's source IP before persisting it. Only the four documented TradingView source IPs (`52.89.214.238`, `34.212.75.30`, `54.218.53.128`, `52.32.178.7`) MAY be accepted.

#### Scenario: Valid secret and IP

- GIVEN a request carries the correct shared secret and originates from `52.89.214.238`
- WHEN the webhook is received
- THEN the request is accepted for further processing

#### Scenario: Wrong source IP rejected

- GIVEN a request carries the correct shared secret but originates from an IP outside the documented set
- WHEN the webhook is received
- THEN the system MUST reject the request with a 4xx response and MUST NOT persist it

#### Scenario: Missing or wrong secret rejected

- GIVEN a request omits the shared secret or supplies the wrong one
- WHEN the webhook is received
- THEN the system MUST reject the request with a 4xx response and MUST NOT persist it

### Requirement: Idempotent Signal Persistence

The system MUST require an explicit idempotency field in the alert payload. The stored idempotency key is derived from `(strategy_id, idempotency field)`, enforced by a database unique constraint.

#### Scenario: Missing idempotency field

- GIVEN an authenticated request whose payload lacks the idempotency field
- WHEN the webhook is received
- THEN the system MUST reject the request with a 4xx response and MUST NOT persist it or enqueue a job

#### Scenario: First delivery of a signal

- GIVEN an authenticated request with a valid, previously-unseen idempotency key
- WHEN the webhook is received
- THEN the system MUST persist exactly one signal row and enqueue exactly one job

#### Scenario: Duplicate delivery of the same signal

- GIVEN a signal with idempotency key `K` was already persisted
- WHEN a request with the same `K` is received again
- THEN the system MUST NOT create a second signal row or a second job
- AND the system MUST return 200 with the same response shape as the original acceptance

### Requirement: Fast Enqueue-Only Response

The system MUST return a response well under TradingView's 3-second cancellation window and MUST NEVER execute a trade within the request/response cycle. Persistence and enqueue are the only side effects.

#### Scenario: Accepted signal returns fast

- GIVEN a valid, authenticated, non-duplicate signal
- WHEN the webhook is received
- THEN the system persists the signal, enqueues a job, and returns 200 without invoking any exchange adapter

#### Scenario: No inline execution under any outcome

- GIVEN any webhook request, accepted or rejected
- WHEN the request/response cycle completes
- THEN no trade execution occurs within that cycle; execution happens only later, in a worker
