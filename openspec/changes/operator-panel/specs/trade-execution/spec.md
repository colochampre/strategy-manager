# Delta for Trade Execution

> **Added 2026-10-04 (owner decision 45; design addendum "the simulated exchange
> fills at the alert's price", §§ A-N).**
>
> This delta extends `openspec/specs/trade-execution/spec.md`. This change
> touches that spec because decision 45 changes what a simulated fill is: from
> this change on, under `DRY_RUN`, a fill is priced at the price its alert
> carried and carries the venue's taker fee, where before every simulated fill
> was priced 1 with no fee. Decision 43's rehearsal list (this change's
> `performance-reporting`, `admin-api` and `operator-panel` deltas) reads those
> rows.
>
> **No requirement of the main spec is revised.** The main spec's only
> requirement about dry run, "DRY_RUN Safety", says which adapter is used and
> that the default is true; it says nothing about how a simulated fill is priced
> or charged, and it stays correct as written. Every requirement below is
> ADDED. Their pools are the two the product enables: `(bybit, usdt-m, USDT)` and
> `(binance, usdt-m, USDT)`.
>
> Terms. The "alert's stored price" is `signals.price` as read back from the
> database (a price with more than 18 decimal places is rounded to 18 once, at
> ingress, by the column). A "simulated fill" is a fill minted by the simulated
> exchange under `DRY_RUN`; its fill id starts with `fake-fill-`. A symbol has
> three spellings: the alert `STXUSDT.P`, the venue's bare `STXUSDT`, Pionex
> `STXUSDT_PERP`.

## ADDED Requirements

### Requirement: A Simulated Fill Is Priced At The Alert's Stored Price

Under `DRY_RUN`, in pool `(bybit, usdt-m, USDT)` and in pool
`(binance, usdt-m, USDT)`, the simulated exchange MUST price every fill at the
stored price of the alert behind the order, EXACTLY: an opening fill at the
stored price of the opening alert, a closing fill at the stored price of the
alert that causes the close. It MUST NOT round, quantise to a tick, simulate
slippage or substitute any other price. For a REVERSE, the close of the old
allocation and the open of the new one MUST both be priced at the reversing
alert's stored price. A closing order with no closing alert of its own (an
orphan closed by an opening alert, which carries no signal id) MUST be priced at
the stored price of the alert that found the orphan, never at the price of the
alert that opened the position. Each order MUST keep its own price when several
orders are built before any is placed. The price MUST NOT size a close: a close's
size remains the ledger's net.

#### Scenario: An opening fill equals an 18-decimal alert price to the last place

- GIVEN pool `(bybit, usdt-m, USDT)` under `DRY_RUN` and an opening order whose alert's stored price is `0.123456789012345678`
- WHEN the simulated exchange fills the order
- THEN the fill's price is exactly `0.123456789012345678`, equal as a decimal and as text

#### Scenario: A 19-decimal alert price is filled at the stored 18-decimal value

- GIVEN pool `(bybit, usdt-m, USDT)` under `DRY_RUN` and a webhook alert with symbol `STXUSDT.P` and price `"0.1234567890123456789"` (19 places), whose stored price is therefore `0.123456789012345679`
- WHEN the signal is processed and its opening fill is settled into the ledger
- THEN the fill's price and the ledger row's `price` both equal the stored `signals.price` of the signal the reservation names, exactly (`0.123456789012345679`), the row's market key is `STXUSDT`, and its fill id starts with `fake-fill-`

#### Scenario: A Binance opening fill is priced at the alert

- GIVEN pool `(binance, usdt-m, USDT)` under `DRY_RUN` and an opening alert `STXUSDT.P` whose stored price is `0.4512`
- WHEN the order is filled
- THEN the fill's price is exactly `0.4512`

#### Scenario: A close is priced at the closing alert, not at the opening one

- GIVEN pool `(bybit, usdt-m, USDT)` holds a rehearsal LONG on `STXUSDT` opened by an alert at `0.4512`
- WHEN a closing alert `STXUSDT.P` with stored price `0.4633` is processed
- THEN the closing fill's price is exactly `0.4633`, and the allocation nets to zero

#### Scenario: A REVERSE prices both halves at the reversing alert

- GIVEN pool `(bybit, usdt-m, USDT)` holds a rehearsal LONG on `STXUSDT` opened at `0.4512`, and a reversing alert whose stored price is `0.4633`
- WHEN the close half settles and the open half is placed
- THEN the close fill and the new allocation's opening fill are both priced exactly `0.4633`, and the opening fill equals the stored price of the signal its reservation names

#### Scenario: An orphan close is priced at the alert that found it

- GIVEN pool `(bybit, usdt-m, USDT)` holds a rehearsal orphan on `STXUSDT` opened at `0.4512`, and an opening alert on the same market with stored price `0.4633` finds it
- WHEN the orphan is closed before the opening alert's own order is placed
- THEN the orphan's closing fill is priced exactly `0.4633`, although the close carries no signal id

#### Scenario: Two orders built before either is placed each fill at their own price

- GIVEN orders X (alert price `0.4512`) and Y (alert price `0.4633`) were both built before either was placed
- WHEN Y is placed and then X is placed
- THEN Y's fill is priced `0.4633` and X's fill is priced `0.4512`

#### Scenario: An alert priced exactly 1 is filled at 1 because the alert said so

- GIVEN an opening alert whose stored price is exactly `1`
- WHEN the order is filled
- THEN the fill's price is `1`, and a later close whose alert carried `0.4633` is filled at `0.4633`, not at 1

### Requirement: An Order With No Usable Price Is Refused, Never Defaulted

A price is usable only when it is finite and above zero. Under `DRY_RUN`, the
simulated exchange MUST refuse a CLOSING order whose reference price is absent,
not finite or not above zero, and an order it did not build itself, by raising
the venue-rejection error from placement: no fill is minted; the close attempt
is marked FAILED, or an opening reservation is released; when the order has a
signal, that signal ends `REJECTED` (`CLOSE_REJECTED_BY_VENUE` for a close,
`ORDER_REJECTED_BY_VENUE` for an open); the ledger is unchanged; and exactly one
ERROR is logged by the caller, naming the cause. An absent price MUST NOT be read
as zero, and the price MUST NEVER be replaced by 1, by the entry price, by the
last price seen, or by any other fallback. An OPENING order whose price is not
usable keeps today's behaviour in both modes: the domain refuses to size it
before any fill exists, so no fill is minted, and this requirement adds no
fallback to it. A positive price, however absurd, MUST be filled at.

#### Scenario: A close with no reference price is refused

- GIVEN pool `(bybit, usdt-m, USDT)` holds a rehearsal LONG on `STXUSDT` and a close is built with an absent reference price
- WHEN the simulated exchange is asked to place it
- THEN it raises the venue-rejection error, no fill exists for that client order id, the attempt is FAILED, the signal is `REJECTED` with `CLOSE_REJECTED_BY_VENUE`, the ledger gains no row, and exactly one ERROR is logged naming the cause

#### Scenario: Zero, negative, NaN and infinite close prices are each refused

- GIVEN pool `(binance, usdt-m, USDT)` holds a rehearsal LONG on `STXUSDT`
- WHEN a close is placed with reference price `0`, then `-0.4633`, then `NaN`, then `Infinity`
- THEN each is refused exactly as in the previous scenario, each with no fill and no ledger row, and none is filled at 1

#### Scenario: A refused close leaves the position open for the next opening alert

- GIVEN a close for pool `(bybit, usdt-m, USDT)`'s allocation A1 was refused for an absent price, so A1 is still open in the ledger
- WHEN the strategy's next opening alert on the same market, with stored price `0.4633`, finds A1 as an orphan
- THEN A1 is closed by a fill priced `0.4633` and nets to zero

#### Scenario: An orphan close refused for its price writes no outcome on a signal

- GIVEN an orphan close (no signal id) in pool `(bybit, usdt-m, USDT)` is built with an absent reference price
- WHEN it is placed
- THEN it is refused with no fill, the attempt is FAILED, one ERROR is logged, and the close writes no signal outcome of its own

#### Scenario: An order the simulated exchange did not build is refused

- GIVEN an order for pool `(bybit, usdt-m, USDT)` whose client order id the simulated exchange never saw built
- WHEN it is placed
- THEN the venue-rejection error is raised, no fill exists, an opening reservation is released and its signal ends `REJECTED` with `ORDER_REJECTED_BY_VENUE`

#### Scenario: An opening alert with a non-positive price never reaches a fill

- GIVEN pool `(bybit, usdt-m, USDT)` and an opening order whose price is `0`
- WHEN the order is built
- THEN the domain refuses it, no fill is minted, and no price is substituted

#### Scenario: A positive but absurd price is filled at

- GIVEN a closing alert whose stored price is `9999999.5` on a market that trades near `0.46`
- WHEN the close is placed
- THEN the closing fill is priced exactly `9999999.5`

### Requirement: A Simulated Fill Carries The Venue's Taker Fee In USDT

Under `DRY_RUN`, every simulated fill MUST carry the venue's TAKER fee on its
notional, on the opening fill and on the closing fill, in `USDT`, never in the
base coin and never at a maker rate. The rate for pool `(bybit, usdt-m, USDT)`
MUST be `0.00055` (verified by the real round trip of 2026-08-27) and for pool
`(binance, usdt-m, USDT)` MUST be `0.0005` (the owner's reading of the account on
2026-10-04, not yet confirmed by a real round trip in this project). The fee MUST
be `quantity x fill price x rate`, with the product taken without prior rounding
and then quantised to 18 decimal places, half-even (the scale of the ledger's
`fee` column), so that the fill carries exactly the value the column stores. A
fee below `0.5e-18` MUST quantise to 0. The base quantity MUST be untouched by
the fee, so a close sized from the ledger equals its open and the allocation nets
to zero. A fee rate below 0, or of 1 or more, MUST be refused when a simulated
exchange is built.

#### Scenario: A Bybit round trip is charged 0.00055 on both sides

- GIVEN pool `(bybit, usdt-m, USDT)`, granted capital 564 USDT, an opening alert `STXUSDT.P` at `0.4512` and a closing alert at `0.4633`
- WHEN the position is opened and closed in dry run
- THEN the opening fill is 1250 `STXUSDT` at `0.4512` (notional 564) with fee `0.3102` USDT, the closing fill is 1250 at `0.4633` (notional 579.125) with fee `0.31851875` USDT, both with `fee_currency` USDT, and the allocation nets to zero

#### Scenario: A Binance round trip is charged 0.0005 on both sides

- GIVEN pool `(binance, usdt-m, USDT)` and the same granted capital and alerts as the Bybit scenario
- WHEN the position is opened and closed in dry run
- THEN the opening fill's fee is `0.282` USDT and the closing fill's fee is `0.2895625` USDT, neither at the maker rate `0.0002`

#### Scenario: The fee is subtracted from the PnL and no fee is left out

- GIVEN the Bybit round trip above, written through the production write path
- WHEN the operation's figures are derived
- THEN its fees total `0.62871875` USDT, its PnL is `14.49628125` USDT (579.125 - 564 - 0.62871875), and no fee is reported in another currency

#### Scenario: A fee with more than 18 decimal places is quantised half-even

- GIVEN pool `(bybit, usdt-m, USDT)` and a fill of quantity `10` at price `0.123456789012345678` (notional `1.23456789012345678`)
- WHEN the fee is computed
- THEN it is exactly `0.000679012339567901` USDT (the unrounded product `0.000679012339567901229`)

#### Scenario: A tie rounds to the even digit and a product of more than 28 digits is not pre-rounded

- GIVEN pool `(binance, usdt-m, USDT)` and a fill of quantity `0.000000000000003` at price `1`
- WHEN the fee is computed
- THEN it is `0.000000000000000002` USDT (the product `1.5e-18` rounds to the even digit), and a fill whose product has more than 28 significant digits carries the value rounded once, at 18 places, from the full product

#### Scenario: The fee never touches the holding

- GIVEN a dry-run open in pool `(bybit, usdt-m, USDT)` of 1250 `STXUSDT` with fee `0.3102` USDT
- WHEN the allocation's net base and the pool-wide net position are read, and then after the close
- THEN both read 1250 `STXUSDT` after the open and 0 after the close

#### Scenario: A fee rate outside [0, 1) is refused at construction

- GIVEN a simulated exchange is being built
- WHEN its rate is `-0.00055`, then `1`
- THEN construction is refused each time

### Requirement: A Market Not Quoted In USDT Is Refused In Dry Run

Because the simulated fee is charged in `USDT` and no rate is verified for
another currency (rule 7), the simulated exchange MUST refuse, before minting any
fill, an order whose market is not quoted in USDT, whatever its price, by raising
the venue-rejection error from placement. A market quoted in USDT MUST be
accepted in each spelling `STXUSDT`, `STXUSDT.P`, `STX_USDT` and `STX_USDT_PERP`.
The refusal MUST leave no fill, release an opening reservation or mark a close
FAILED, and log one ERROR naming the cause (the fee is charged in USDT and the
market is not quoted in it). It MUST NOT charge a fee in another currency, and
MUST NOT convert one.

#### Scenario: A BTC-quoted and a USD-quoted market are refused

- GIVEN pool `(bybit, usdt-m, USDT)` under `DRY_RUN`
- WHEN orders on `ETHBTC` and on `BTCUSD` are placed with a usable price
- THEN each is refused with the venue-rejection error, no fill exists, and one ERROR per order names the cause

#### Scenario: Every USDT spelling is filled and charged

- GIVEN pool `(bybit, usdt-m, USDT)` under `DRY_RUN`
- WHEN orders on `STXUSDT`, `STXUSDT.P`, `STX_USDT` and `STX_USDT_PERP` are placed at `0.4512`
- THEN each is filled at `0.4512` and charged the `0.00055` fee in USDT

#### Scenario: A refused opening releases its reservation

- GIVEN an opening alert on `ETHBTC` for pool `(binance, usdt-m, USDT)` whose reservation was taken
- WHEN the order is refused at placement
- THEN the reservation is released, the signal ends `REJECTED` with `ORDER_REJECTED_BY_VENUE`, and the ledger gains no row

### Requirement: An Exchange With No Simulated Fee Rate Is Not Served In Dry Run

Under `DRY_RUN`, a simulated exchange MUST be built only for an exchange that has
a simulated taker fee rate. Today that excludes Pionex: its pools are NOT
tradable in dry run, exactly as they are not tradable live. A signal for a pool of
such an exchange MUST end `REJECTED` with `UNTRADABLE_POOL` before any capital is
reserved, with no reservation and no ledger row, and one WARNING per signal. At
startup the worker MUST still start, MUST log the existing unserved-pools
WARNING for those pools, and MUST log one further WARNING naming the exchange and
the reason ("no simulated taker fee rate is defined for '<exchange>'"). A fee of
zero MUST NEVER be charged because a rate is missing. Bybit and Binance MUST both
always have a rate.

#### Scenario: A signal on a Pionex pool is refused before any reservation

- GIVEN a worker under `DRY_RUN` with a strategy bound to a Pionex pool `(pionex, spot, USDT)`
- WHEN an opening signal for that strategy is processed
- THEN the signal ends `REJECTED` with `UNTRADABLE_POOL`, no reservation exists for it, no ledger row is written, and one WARNING is logged

#### Scenario: The startup says why the pool is unserved and the worker still starts

- GIVEN the same configuration
- WHEN the worker is built
- THEN the existing unserved-pools WARNING is logged, one more WARNING reads "no simulated taker fee rate is defined for 'pionex'", and the worker starts

#### Scenario: Bybit and Binance are still served beside the unserved exchange

- GIVEN the same worker
- WHEN a signal for pool `(bybit, usdt-m, USDT)` and one for pool `(binance, usdt-m, USDT)` are processed
- THEN each is filled by its own simulated exchange

#### Scenario: The rates table holds exactly the two verified rates

- GIVEN the simulated rates table
- WHEN it is read
- THEN it holds Bybit at `0.00055` and Binance at `0.0005`, its fee currency is `"USDT"`, and no other exchange has an entry

### Requirement: A Dry Run Sizes A Position At 1x

Under `DRY_RUN`, in pool `(bybit, usdt-m, USDT)` and pool
`(binance, usdt-m, USDT)`, the simulated exchange MUST size a position at
leverage 1: the position's notional equals the capital granted, and quantity is
the granted amount divided by the alert's stored price, in full, with no step
size, minimum quantity or minimum notional. It MUST NOT read the venue's leverage
for a symbol. A simulated order that has no contract marker on its symbol (a
spot-shaped order) MUST fill the quantity `granted / alert price`. A dry-run
operation's PnL and PnL % MEAN what the reserved capital earns WITHOUT leverage:
one leverage-th of what the same alerts would produce live at the venue's
leverage. Its fee scales the same way, because it is charged on the notional. A
dry-run result MUST NOT be read as a live result.

#### Scenario: A futures open is sized so that its notional equals the capital granted

- GIVEN pool `(bybit, usdt-m, USDT)`, granted capital 564 USDT and an opening alert `STXUSDT.P` at `0.4512`
- WHEN the order is built and filled in dry run
- THEN the fill's quantity is 1250 `STXUSDT` and its notional is 564

#### Scenario: A venue leverage of 3 does not change the dry-run size

- GIVEN the venue would report leverage 3 for `STXUSDT` and the same granted capital and alert
- WHEN the order is filled in dry run
- THEN the quantity is still 1250 (not 3750), and for alerts at `0.4512` then `0.4633` the dry-run gross result is 15.125 USDT where the same alerts at 3x live would give 45.375 USDT

#### Scenario: A spot-shaped buy fills the granted amount divided by the alert's price

- GIVEN pool `(bybit, usdt-m, USDT)` and an opening alert whose symbol `STXUSDT` has no contract marker, granted capital 100 USDT, stored price `0.4`
- WHEN the buy is filled in dry run
- THEN the quantity is 250 `STXUSDT`, the notional is 100 and the fee is `0.055` USDT

### Requirement: A Simulated Fill Changes Nothing The Allocation Engine Reads

A simulated fill, its price, its fee and its result MUST NOT change any pool's
availability, any balance snapshot or any reservation. Availability under
`DRY_RUN` remains the real venue's balance snapshot minus the active
reservations of pool `(exchange, venue, settlement_currency)`. Rehearsal fills
MUST keep their identifying prefixes (`fake-fill-` for a fill, `fake-order-` for
an order) so that they stay recognisable now that their price no longer is, and
MUST stay out of every performance total (owner decision 43).

#### Scenario: A profitable rehearsal moves no availability

- GIVEN pool `(bybit, usdt-m, USDT)` has a balance snapshot of 1000 USDT and no active reservation, and a dry-run round trip (open at `0.4512`, close at `0.4633`, fees `0.62871875` USDT) completes
- WHEN the pool's availability is read afterwards
- THEN the snapshot is still 1000 USDT, the pool's availability is 1000 USDT, and no reservation was created or changed by the fills' prices or fees

#### Scenario: The prefixes are kept and no total counts the fill

- GIVEN the same round trip
- WHEN its ledger rows and every performance total of pool `(bybit, usdt-m, USDT)` are read
- THEN the fill ids start with `fake-fill-` and the order ids with `fake-order-`, and no total includes the operation

### Requirement: Nothing Already In The Ledger Is Repriced

Owner decision 45 MUST apply to fills minted after it takes effect only. A
simulated fill already in the ledger MUST NOT be rewritten, repriced or
re-fee'd, and the ledger remains append-only. A dry-run position open when the
decision takes effect (entered at price 1 with no fee, for example 1250
`STXUSDT` at `1`) MUST be closed by a fill priced at its closing alert's stored
price, against an entry of 1, and that closing fill MUST carry the venue's taker
fee.

#### Scenario: A row written before the change keeps price 1 and fee 0

- GIVEN pool `(bybit, usdt-m, USDT)` holds an opening rehearsal row of 1250 `STXUSDT` at price `1` with fee `0`, written before decision 45 took effect
- WHEN the worker restarts on the new code and other fills are written
- THEN that row still reads price `1` and fee `0`

#### Scenario: A position that straddles the change closes at the alert's price

- GIVEN that open position and a closing alert `STXUSDT.P` with stored price `0.4633`
- WHEN the position is closed in dry run
- THEN the closing fill is 1250 at exactly `0.4633` with fee `0.31851875` USDT (rate `0.00055`), the position nets to zero, and the opening row is unchanged

### Requirement: A Real Adapter's Requests Do Not Depend On The Price Of A Close

What a real adapter sends to a venue MUST be unchanged by decision 45, with or
without the reference price on a close. The reference price is read only by the
simulated exchange; a real adapter MUST NOT read it, send it, or let it
influence any order, size, parameter or signature. This holds for each registered
exchange, `BybitFuturesExchangeAdapter` (pool `(bybit, usdt-m, USDT)`) and
`BinanceFuturesExchangeAdapter` (pool `(binance, usdt-m, USDT)`), and for the
unregistered Pionex adapters' built orders. The order types that real adapters
send MUST carry no price.

#### Scenario: Bybit's request is byte-identical with and without a reference price

- GIVEN `BybitFuturesExchangeAdapter` is driven through the real trade client over a mock transport with a frozen clock, and the same close of `STXUSDT.P` is built and placed once with an absent reference price and once with `0.4633`
- WHEN the two runs' recorded requests are compared
- THEN the two orders are equal and the method, path, query, body bytes and signature are identical, and the request names `STXUSDT`

#### Scenario: Binance's request is byte-identical with and without a reference price

- GIVEN `BinanceFuturesExchangeAdapter` driven the same way
- WHEN the two runs are compared
- THEN the two orders are equal and the method, path, query, body bytes and signature are identical, and the request names `STXUSDT`

#### Scenario: The unregistered Pionex adapters build equal orders

- GIVEN `PionexExchangeAdapter` and `PionexFuturesExchangeAdapter` each build the same close of `STXUSDT_PERP` with and without a reference price
- WHEN the two built orders and the recorded calls are compared
- THEN they are equal

### Requirement: DRY_RUN False Behaves Exactly As Before

With `DRY_RUN=false`, the simulated exchange MUST NOT be registered, no price,
fee or 1x sizing of this decision MUST apply, and every order MUST be sized and
priced by the real adapter exactly as before this decision. The startup refusal
of "DRY_RUN Safety" (no real adapter registered while `dry_run=false`) MUST be
unchanged.

#### Scenario: A live close is sent exactly as before

- GIVEN `DRY_RUN=false` with the real adapter registered for pool `(bybit, usdt-m, USDT)` and a closing alert at `0.4633`
- WHEN the close is built and placed
- THEN the venue request is the same as before this decision, the fill that comes back is the venue's own price and fee, and the simulated exchange is not registered

### Requirement: Simulated Pricing Is Visible In The Log

So that the moment decision 45 took effect and each simulated price and fee are
visible in the journal, the worker MUST log, once at start per process, one INFO
line saying the simulated exchange prices each fill at its alert's price and
naming each simulated exchange with its taker rate. It MUST log one WARNING
naming the exchange and the price instead when a simulated exchange is built with
a fixed price. It MUST log one INFO line per simulated fill with the exchange,
symbol, side, quantity, price, fee and client order id. No log line MUST carry a
credential, a DSN, a token or a raw payload.

#### Scenario: The startup line names each exchange and its rate

- GIVEN a worker under `DRY_RUN` with no fixed price
- WHEN it starts
- THEN one INFO line says each fill is priced at its alert's price and names Bybit with `0.00055` and Binance with `0.0005`

#### Scenario: A fixed price is a startup WARNING

- GIVEN a simulated exchange for Bybit is built with a fixed price of `1`
- WHEN the worker starts
- THEN one WARNING names `bybit` and the price `1`

#### Scenario: Each simulated fill is logged once with its price and fee

- GIVEN a simulated fill of 1250 `STXUSDT` bought at `0.4512` with fee `0.3102` USDT in pool `(bybit, usdt-m, USDT)`
- WHEN it is minted
- THEN one INFO line carries `bybit`, `STXUSDT`, BUY, `1250`, `0.4512`, `0.3102` and the client order id, and no credential
