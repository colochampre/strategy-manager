# Job Queue Specification

## Purpose

A PostgreSQL-backed job queue shared across modules, used for signal processing and the reservation-expiry sweeper. Row locks tie job visibility to the owning connection so crashed workers never require a separate visibility-timeout mechanism.

## Requirements

### Requirement: SKIP LOCKED Claim

The system MUST claim jobs using `FOR UPDATE SKIP LOCKED` so that concurrent workers never block on each other and never claim the same job.

#### Scenario: Concurrent workers claim distinct jobs

- GIVEN two available jobs and two workers polling concurrently
- WHEN both workers attempt to claim a job at the same time
- THEN each worker claims a distinct job and neither blocks on the other

#### Scenario: No available jobs

- GIVEN no unclaimed jobs exist
- WHEN a worker polls
- THEN the worker claims nothing and returns without error

### Requirement: Crash Reclaim

A job claimed by a worker whose connection terminates before acknowledgement MUST become claimable again automatically, without requiring a separate visibility-timeout process.

#### Scenario: Worker crashes mid-processing

- GIVEN a worker has claimed a job inside an open transaction
- WHEN that worker's connection terminates before commit
- THEN the row lock releases with the connection and the job becomes claimable by another worker

### Requirement: Acknowledge and Retry

The system MUST support marking a claimed job as completed (ack) and MUST support making a failed job available for retry.

#### Scenario: Successful processing acknowledges the job

- GIVEN a worker has claimed a job and processed it successfully
- WHEN the worker commits its result
- THEN the job is marked complete and is never claimed again

#### Scenario: Failed processing allows retry

- GIVEN a worker has claimed a job and processing fails
- WHEN the worker reports the failure
- THEN the job becomes claimable again for a subsequent attempt

### Requirement: Continuation Scheduling

The system MUST support a continuation that opens a position for a signal in pool `(exchange, venue, settlement_currency)` only after every awaited close settles FILLED. Waiting MUST be driven by polling the database, never the venue, on a cadence of its own rather than by the failure backoff.

#### Scenario: Opens after the awaited close fills

- GIVEN a continuation seeded with an awaited close that is SUBMITTED
- WHEN that close is filled
- THEN the continuation polls and opens the position

#### Scenario: Does not open when any awaited close ends FAILED

- GIVEN a continuation seeded with an awaited close
- WHEN that close ends FAILED
- THEN the continuation abandons and never opens the position

### Requirement: Continuation Abandonment

A continuation MUST be abandoned, opening nothing: with a WARNING when a newer signal for the same strategy AND symbol has arrived (A3); with a WARNING when the originating signal is older than `delayed_open_max_signal_age_seconds` (default 600); with an ERROR when an awaited close has not settled within `open_after_close_settle_timeout_seconds` (default 300) of its creation; with an ERROR when an awaited close ends FAILED.

#### Scenario: Newer signal for the same strategy on the same symbol abandons

- A newer signal for the same strategy and symbol → abandoned with WARNING

#### Scenario: A newer signal for a different symbol does not abandon

- A newer signal for the same strategy on a DIFFERENT symbol MUST NOT abandon it

#### Scenario: 12-minute-old signal abandons

- 12-minute-old signal → abandoned with WARNING

#### Scenario: 4-minute-old signal whose close fills opens

- 4-minute-old signal whose close fills → opens

#### Scenario: Close not settled within 300s abandons

- An awaited close has not settled within 300s of its creation → abandoned with ERROR

### Requirement: Continuation Idempotency

Retrying or re-running a continuation MUST NEVER submit more than one open for the same signal, and a crash between committing a poll and acknowledging its job MUST NOT fork the continuation into two.

#### Scenario: Open never submitted twice for the same signal

- GIVEN a continuation seeded for signal S1
- WHEN it polls and decides to open
- THEN exactly one opening attempt is recorded for S1, never two

#### Scenario: Crash between poll commit and job ack does not fork

- GIVEN a continuation has committed a poll result but crashes before acknowledging the job
- WHEN the job is reclaimed
- THEN the same poll step is re-run without forking the continuation chain
