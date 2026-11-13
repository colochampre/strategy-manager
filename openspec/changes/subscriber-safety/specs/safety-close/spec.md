# Safety Close Specification

## Purpose

A subscriber's position must not depend on an alert that may never come.
Under D2, an author cannot stop a strategy that has positions open. If one is
stopped anyway, every open position on it is closed at once. Under D8, a
subscriber can close a position from the panel.

## Requirements

### Requirement: A strategy with open positions cannot be disabled

Disabling a strategy MUST be refused while anyone holds exposure on it, as
archiving already is:

- a non-zero position in the ledger;
- a live reservation;
- a SUBMITTED execution attempt.

The refusal is `OpenPosition` (409) and names the exposure. It MUST use the
same exposure reading (`StrategyExposureAdapter`) and the same lock order as
`ArchiveStrategy`: the pool advisory locks first, then the strategy row. An
opening and a disable racing each other therefore cannot both win.

Enabling is never refused for exposure.

#### Scenario: Disable refused
- GIVEN an enabled strategy and a subscriber holding a position on it
- WHEN its author disables it
- THEN the request is refused with 409 `OpenPosition`, and the strategy stays enabled

#### Scenario: Disable allowed when flat
- GIVEN an enabled strategy with no exposure
- WHEN its author disables it
- THEN it is disabled

#### Scenario: An opening racing a disable
- GIVEN a disable holding the pool lock
- WHEN an opening on the same pool waits for that lock
- THEN either the disable commits and the opening is skipped as disabled, or the opening commits first and the disable is refused

### Requirement: A stopped strategy's positions are closed at once

If a strategy is disabled, archived or authorless while positions remain
open on it, every one of them MUST be closed at market at once, without
waiting for a signal (D2). Each close goes through `ClosePosition`, sized
from the ledger, with no signal and the cause `SAFETY_CLOSE`.

The system may reach that state despite the refusal above, through:

- an operator action;
- the author's account deletion;
- a state that predates this change.

So the reservation sweep MUST check for it on every run, as a backstop. Each
position closed this way records a `STRATEGY_STOPPED_CLOSED` safety event for
its user.

#### Scenario: A disabled strategy with a position
- GIVEN a disabled strategy and a subscriber still holding 0.5 SOL on it
- WHEN the sweep runs
- THEN a reduce-only market close of 0.5 SOL is sent for that allocation
- AND a `STRATEGY_STOPPED_CLOSED` event is recorded for the subscriber

#### Scenario: The close is not repeated
- GIVEN a safety close already SUBMITTED for an allocation
- WHEN the sweep runs again
- THEN no second close is sent for it

### Requirement: A user can close their own position from the panel

A user MUST be able to close one of their own open allocations at market
from the panel (D8). This covers subscribers and authors alike: the author
trades through a subscription too.

- The request names the allocation. An allocation of another user MUST be
  refused as not found.
- The close goes through `ClosePosition`, sized from the ledger, with the
  cause `MANUAL`, in the mode the allocation's reservation records.
- A second request while a close of that allocation is in flight MUST send
  no second order.
- The seat is left as it is: an ACTIVE seat takes the strategy's next
  opening. *Assumption.*
- A `MANUAL_CLOSE` safety event is recorded. *Assumption:* it is listed
  with the others, so the user's history stays whole.

The panel MUST ask for confirmation first, naming the symbol and the size.
Owner, 2026-11-12: "El boton de cerrar ahora debe pedir confirmacion".

#### Scenario: Confirmation first
- GIVEN a user on their open positions
- WHEN they press "Close now" on one
- THEN a dialog names the symbol and the size, and nothing is sent yet
- AND only confirming it sends the close; cancelling sends nothing

#### Scenario: A subscriber closes a position
- GIVEN a subscriber holding 76 DOGE on a strategy
- WHEN they confirm "Close now" on that position
- THEN a reduce-only market close of 76 DOGE is sent for that allocation
- AND the position leaves the open positions once its fill is recorded

#### Scenario: Another user's allocation
- WHEN a user asks to close an allocation that is not theirs
- THEN the request is refused as not found, and nothing is sent

#### Scenario: Double click
- GIVEN a close of an allocation in flight
- WHEN the same user asks to close it again
- THEN no second order is sent
