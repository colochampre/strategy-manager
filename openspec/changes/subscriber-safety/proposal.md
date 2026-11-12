# Subscriber safety

A subscriber's open position depends entirely on the author's next signal.
`Leave` stops new openings, but the position "runs until the strategy closes
it" (`subscriptions/application/leave.py:16`). `ClosePosition` only fires on a
strategy's signal. Nothing in the app closes a subscriber's position if the
author disables the strategy, edits or deletes their TradingView alert, or
simply stops. Today the only way out is closing it by hand at the exchange;
reconciliation then finds the difference and proposes booking it.

Owner, 2026-11-12: "va a haber que planificar medidas de seguridad para los
suscriptores. Un cierre manual no puede ser la única medida de seguridad. Un
usuario que no entra al panel no puede cerrar a mano."

It is also a prerequisite of `account-deletion`: an author must not be able to
leave subscribers holding positions no signal will close.

## Layers, strongest first

1. **A protective stop at the exchange.** A reduce-only stop order placed with
   every live opening. It is the only layer that still works when the user
   never signs in, the author vanishes, and this app or its server is down.
   It needs the venue APIs verified live, as every venue fact here has been.
   Bybit's position trading-stop and Binance's reduce-only `STOP_MARKET` are
   the candidates.
2. **Automatic closing of orphaned positions.** The app closes a subscriber's
   open position by itself, after a grace period, when its strategy:
   - is disabled or archived;
   - loses its author (account deletion);
   - stays silent beyond a threshold while subscribers hold positions.

   This uses the same `ClosePosition`, sized from the ledger.
3. **A manual "Close now"** per position, for the subscriber.
4. **Notice.** The subscriber is told when a stop fires, when an orphaned
   position is closed, and when a strategy they follow is disabled. In the
   panel first. E-mail needs an outbound provider the app does not have yet
   (there is no outbound e-mail today).

## Open decisions (asked one at a time)

- D1: is the exchange stop mandatory for every live opening, and who sets its
  level?
- D2: the grace period before an orphaned position is closed.
- D3: what counts as silence: a threshold the author declares, or one derived
  from the strategy's own history.
- D4: e-mail notices now (outbound provider) or later.

## Out of scope

- Take-profit orders.
- Trailing stops.
