# Protective Stop Specification

## Purpose

Every live futures opening carries a stop loss that rests at the exchange, so
a position is protected when its user never signs in, its author stops
signalling, or this system is down (decision D1). The venue facts this relies
on were verified live on 2026-11-12 (`tasks.md`, SS.1, runs 1-6).

Decisions D5-D7 (owner, 2026-11-12) are recorded in `proposal.md`. Every rule
marked *Assumption* is open to the owner's correction.

## Requirements

### Requirement: A strategy carries one stop level, as a percentage of price

A strategy MUST carry `stop_loss_pct`, the distance from the entry price at
which its positions are stopped, as a percentage of price (D5). Its author
sets it, and MAY change it at any time. A change MUST apply to openings made
after it only. A stop already at the exchange MUST stay where it was placed.

*Assumption:* the accepted range is 1 to 50, with at most two decimals.

Every strategy that exists when this change deploys MUST receive 10 (D6).

#### Scenario: Author sets the level
- GIVEN a strategy whose author is signed in
- WHEN the author saves a stop level of 7.5
- THEN the strategy's `stop_loss_pct` is 7.5
- AND the next live opening on it places its stop 7.5% from its entry

#### Scenario: A level out of range is refused
- WHEN an author saves a stop level of 0.5 or 60
- THEN the save is refused with a field error, and the level is unchanged

#### Scenario: A changed level leaves resting stops alone
- GIVEN an open position whose stop rests at the exchange 10% below entry
- WHEN the author changes the level to 5
- THEN that stop stays where it is, and no request reaches the exchange

#### Scenario: Existing strategies at deploy
- WHEN the migration runs
- THEN every existing strategy has `stop_loss_pct` 10

### Requirement: The stop caps the leverage a seat can choose

Under isolated margin, a position is liquidated after a price move of about
`1 / leverage` minus the maintenance margin. A stop that lies beyond the
liquidation price never fires. So a seat's leverage MUST NOT exceed
`max_leverage(stop_loss_pct) = min(20, floor(100 / (stop_loss_pct + 1)))`.
The extra point is a buffer for maintenance margin. *Assumption:* the formula
and the one-point buffer. 10 gives 9x, and 5 gives 16x.

- Subscribing, or changing a seat's leverage, above the cap MUST be refused
  (`LEVERAGE_ABOVE_STOP_CAP`). The panel's leverage control MUST NOT offer a
  value above the cap.
- A seat whose leverage is above the cap can only have been set before the
  author widened the stop. Such a seat MUST have its live openings refused
  (`LEVERAGE_ABOVE_STOP_CAP`) before any capital is reserved, and the refusal
  MUST be recorded as a safety event so its user learns of it. Its leverage
  MUST NOT be changed for the user.

#### Scenario: The cap follows the level
- GIVEN a strategy with `stop_loss_pct` 10
- WHEN a user subscribes at 12x
- THEN the subscription is refused with `LEVERAGE_ABOVE_STOP_CAP`, naming 9x as the maximum

#### Scenario: A widened stop leaves a seat above its cap
- GIVEN a seat at 9x on a strategy at 10
- AND the author changes the level to 15, which caps leverage at 6x
- WHEN the next opening signal reaches that seat
- THEN no capital is reserved and no order is sent
- AND a safety event `OPENING_REFUSED_LEVERAGE_CAP` is recorded for that user
- AND the seat's leverage is still 9x

### Requirement: Bybit places the stop on the opening order itself

On Bybit, the opening order MUST carry the stop:

- the fields `stopLoss`, `slTriggerBy`, `tpslMode: Full` and
  `slOrderType: Market`;
- the level computed from the price the order is built against: below it for
  a LONG, above it for a SHORT;
- the level rounded to the symbol's tick, away from the entry.

There MUST NOT be a moment in which the position exists without its stop
(run 4).

After the opening fills, the system MUST find the resting stop:

- it is the conditional order whose `parentOrderLinkId` is the opening's
  `orderLinkId`;
- its `orderId` is recorded as the stop's venue id, the id its execution
  carries when it fires (run 2).

If no resting stop is found, the stop is treated as failed, as in the
Binance requirement below.

*Assumption:* the trigger is `MarkPrice`, which is the price liquidation
reads. Runs 1-6 used `LastPrice` and `CONTRACT_PRICE`. Both venues accept
both triggers.

#### Scenario: A LONG opens with its stop
- GIVEN a strategy at 10 and a live LONG opening built against 80.00 on a 0.01 tick
- WHEN the order is sent
- THEN it carries `stopLoss` "72.00", `tpslMode` "Full" and `slOrderType` "Market"
- AND after the fill the stop's `orderId` is recorded against the allocation

#### Scenario: A SHORT's stop is above
- GIVEN a strategy at 10 and a live SHORT opening built against 80.00
- WHEN the order is sent
- THEN it carries `stopLoss` "88.00"

### Requirement: Binance places the stop right after the fill

Binance has no stop on the opening order.

- Once the opening's fills are recorded, the system MUST send
  `POST /fapi/v1/algoOrder` with these fields:
  - `algoType: CONDITIONAL` and `type: STOP_MARKET`;
  - `side` opposite to the position;
  - `triggerPrice` computed from the average fill price, rounded to the tick
    away from the entry;
  - `workingType` per the trigger assumption above;
  - `closePosition: true`;
  - `clientAlgoId`, a UUID recorded BEFORE the request is sent.
- A `-2013 Order does not exist` on reading a just-placed stop MUST be
  retried, and MUST NOT be read as a missing stop (run 5: it was there).
- A POST whose outcome is unknown, such as a timeout or a 5xx, MUST be
  resolved by reading the stop back by its `clientAlgoId` before anything
  else is decided.

#### Scenario: The stop follows the fill
- GIVEN a live LONG on DOGEUSDT filled at an average of 0.066340, a 0.000010 tick and a strategy at 10
- WHEN the fills are recorded
- THEN an algo order is sent with `triggerPrice` "0.059706", `side` SELL and `closePosition` "true"
- AND its `clientAlgoId` was stored before the request

#### Scenario: A lagging read is retried
- GIVEN a stop acknowledged with an `algoId`
- WHEN the first read of it answers `-2013`
- THEN the read is retried, and the stop is not treated as failed

### Requirement: A position whose stop could not be placed is closed at once

When placing the stop fails definitively, or no resting stop can be found
after the retries, the system MUST close the position at market at once,
through `ClosePosition`, sized from the ledger (D7). It MUST record a
`STOP_FAILED_CLOSED` safety event and alert the operator at ERROR: the venue
refusing a stop is a fault the operator must see. No position may stay open
without its stop.

#### Scenario: Binance refuses the stop
- GIVEN a live LONG whose fills are recorded
- WHEN `POST /fapi/v1/algoOrder` is refused definitively
- THEN a reduce-only market close of the whole ledger size is sent
- AND a `STOP_FAILED_CLOSED` event is recorded for that user
- AND the operator is alerted

### Requirement: A fired stop is booked by the system, not by reconciliation

A worker job MUST read every resting stop of a live allocation at an interval
shorter than the reconciliation scan. *Assumption:* every 30 seconds.

- On Bybit, a fired stop is found by the executions whose `orderId` is the
  recorded stop id.
- On Binance, the algo order is read by `clientAlgoId`. A `FINISHED` stop
  names an `actualOrderId`, and its fills are read from
  `/fapi/v1/userTrades?orderId=` (run 5).

The fills of a fired stop MUST be written to the ledger:

- under the stop's allocation;
- on an execution attempt whose cause is `STOP`;
- with the fee in USDT, as reported.

A `STOP_FIRED` safety event MUST be recorded. A fired stop MUST NOT produce a
reconciliation discrepancy alert or a booking proposal.

A stop that is gone because its position closed by other means (a Bybit stop
no longer resting, or a Binance `EXPIRED`) MUST be marked gone and book
nothing (runs 3, 4 and 6).

#### Scenario: A Binance stop fires
- GIVEN a resting Binance stop recorded for an allocation holding 76 DOGE
- WHEN the algo order reads `FINISHED` with `actualOrderId` 105975543111
- THEN a SELL of 76 at the fill price, with the fill's fee, is written to that allocation's ledger
- AND the allocation is flat in the projection
- AND a `STOP_FIRED` event is recorded for the user
- AND reconciliation reports no discrepancy for that symbol

#### Scenario: A stop that went with its position books nothing
- GIVEN a resting stop for an allocation
- WHEN the strategy's close fills and the stop reads `EXPIRED`
- THEN the stop is marked gone, and no ledger row is written for it

### Requirement: A close after a fired stop does nothing

A strategy's close, or any other close, that reaches an allocation already
closed by its stop MUST send no order. It MUST end with an
`ALREADY_CLOSED_BY_STOP` outcome, and MUST NOT retry. A reduce-only close
refused because the venue position is already flat MUST be classified as
`ALREADY_FLAT`, not as a failure, and the stop watcher books the stop's fill.

#### Scenario: The strategy closes after the stop
- GIVEN an allocation whose stop fired and was booked
- WHEN the strategy's close signal arrives for it
- THEN no order is sent, and the delivery ends `ALREADY_CLOSED_BY_STOP`

#### Scenario: The stop fires while the close is in flight
- GIVEN a close sent while the stop fires at the venue
- WHEN the venue refuses the reduce-only close because the position is flat
- THEN the close ends `ALREADY_FLAT` with no operator alert
- AND the stop's fill is booked by the stop watcher

### Requirement: Resting a stop is part of a live adapter's contract

A live FUTURES adapter MUST be able to rest a stop, as described above,
before it is registered with `VenueExchangeRegistry`. A spot venue is outside
this requirement (D9). No refusal path is needed: a
venue without a registered adapter already raises, with no fallback. Today
only Bybit and Binance are registered. The Pionex adapters are not
(`main.py:1203-1212`), and no Pionex key can be saved, because no key
inspector serves Pionex.

A simulated opening MUST record the stop level it would have used, and MUST
NOT place or simulate a stop. *Assumption:* the simulated venue does not fire
stops.

#### Scenario: A simulated opening
- GIVEN a user in SIMULATION
- WHEN an opening fills
- THEN the stop level is recorded, and no stop is placed
