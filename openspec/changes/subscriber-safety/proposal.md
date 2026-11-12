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

## Decisions

- D1 **decided** (owner, 2026-11-12, "Mandatory, author sets"): every live
  opening places the stop at the exchange, at one level the author fixes for
  the whole strategy. *Assumption: a change of level applies to new openings
  only; a stop already at the exchange stays where it was placed.*
- D2 **decided** (owner, 2026-11-12): "Diría Immediately, aunque si un autor no
  puede deshabilitar ni archivar mientras hay posiciones abiertas, es una buena
  medida de seguridad. Si por cualquier motivo el autor logra deshabilitar,
  archivar o borrar su cuenta con posiciones abiertas, se cierran inmediatamente
  sin depender de una alerta que no se sabe si va a llegar". So, two rules:
  - disabling, archiving and deleting the account are REFUSED while anyone holds
    a position on the author's strategy (archive already refuses; disable and
    deletion must too). An author who wants to stop closes first, then disables;
  - if a strategy still ends up disabled, archived or authorless with positions
    open, the app closes every one of them at once, at market, without waiting
    for an alert.
- D3 **decided** (owner, 2026-11-12, "No silence rule"): a strategy that stays
  enabled but stops signalling is covered by the exchange stop alone. A position
  that never reaches the stop stays open until a signal, a manual close or one
  of the D2 events. Layer 2 therefore closes on disable, archive and account
  deletion only.
- D4 **decided** (owner, 2026-11-12): notices are delivered by a notifications
  system the owner is about to request as its own change: "un sistema de
  notificaciones, con las aperturas y cierres de las estrategias suscritas, con
  opción de recibirlas por Telegram, WhatsApp, email o solo la app. El usuario
  elije donde recibirlas". This change records each safety event (stop fired,
  position closed because its strategy was disabled, archived or lost its
  author) and shows it in the panel. Delivery to other channels belongs to
  `notifications`, which must carry these events too.

## Out of scope

- Take-profit orders.
- Trailing stops.
