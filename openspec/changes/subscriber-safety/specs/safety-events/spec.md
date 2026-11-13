# Safety Events Specification

## Purpose

A user must learn what happened to their position without having been
there. This change records each safety event and shows it in the panel. The
`notifications` change delivers the same events to other channels (D4).

## Requirements

### Requirement: Safety events are recorded, append-only, per user

Every event below MUST be recorded as one row:

- `STOP_FIRED`;
- `STOP_FAILED_CLOSED`;
- `STRATEGY_STOPPED_CLOSED`;
- `MANUAL_CLOSE`;
- `OPENING_REFUSED_LEVERAGE_CAP`.

Each row holds:

- the user;
- the kind;
- the strategy;
- the allocation, where there is one;
- the exchange, venue and symbol;
- when it happened;
- a detail, for example the stop level or the size closed.

Rows are never updated or deleted. Each row is written in the same
transaction as the change it reports, so an event exists exactly when its
cause does.

#### Scenario: A fired stop is recorded once
- GIVEN a stop whose fill the watcher books
- WHEN the watcher runs again over the same stop
- THEN there is still exactly one `STOP_FIRED` row for it

### Requirement: A user sees their own events in the panel

The panel MUST list the signed-in user's safety events, newest first, with
the kind, the strategy, the symbol, the time and the detail. All text goes
through i18n, in EN and ES. A user MUST NOT see another user's events, and
an admin sees only their own.

#### Scenario: Only one's own
- GIVEN events recorded for two users
- WHEN one of them opens the list
- THEN only their own events are shown
