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
