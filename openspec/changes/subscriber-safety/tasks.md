# Subscriber safety — tasks

Planning. Decisions made; nothing is built until the owner says to build. It goes before `account-deletion`.

## Tasks

- [x] SS.0 Decisions D1-D4 (owner, 2026-11-12), recorded in `proposal.md`.
- [ ] SS.1 Verify the exchange stop live on Bybit and Binance with a probe that
  signs from the vault (`scripts/probe_credentials.py`, `--user-email`): order
  shape, reduce-only, how a stop's fill is reported, and how it is cancelled
  when the strategy closes first.
  - *Run 1, Bybit, 2026-11-12, `--mode trigger` (PR #103's
    `scripts/check_bybit_stop.py`), not triggered:* SOLUSDT LONG 0.2 at 81.4,
    1x. The price rose to 81.75 and never reached the stop at 81.27; after 15
    minutes the stop was cancelled and the position closed. The account ended
    flat with no stop resting, +0.038 USDT. What was seen:
    - `POST /v5/position/trading-stop` with `tpslMode: Full`, `positionIdx: 0`,
      `slOrderType: Market` answers `{}`.
    - The stop rests as a conditional order under `orderFilter=StopOrder`:
      - `stopOrderType: StopLoss`, `createType: CreateByStopLoss`;
      - `orderStatus: Untriggered`, `triggerPrice: 81.27`,
        `triggerBy: LastPrice`, `triggerDirection: 2`;
      - `reduceOnly: true`, `closeOnTrigger: true`;
      - `qty` equals the whole position (Full mode);
      - `orderLinkId: ""`. A stop carries no client id of ours.
    - On that order `stopLoss` and `slTriggerBy` come back empty. The level is
      in `triggerPrice`/`triggerBy`, and the position object reports
      `stopLoss: '81.27'`.
    - `stopLoss: "0"` answers `{}`. Whether the cancel alone removed the stop
      is not yet separated from the close that followed it: `--mode cancel`
      answers that.
  - *Run 2, Bybit, 2026-11-12, `--mode trigger --stop-pct 0.05`, TRIGGERED:*
    SOLUSDT LONG 0.2 at 81.59, 1x. The stop was set at 81.54 and fired about
    a minute later.
    - The execution carries `orderLinkId: ""`, but its `orderId` is the
      resting stop's own `orderId` (`e93b3d2a…`). Recording that id when the
      stop is set is how the ledger recognises the fill, without
      reconciliation.
    - It is marked by `stopOrderType: StopLoss`, `createType: CreateByStopLoss`
      and `closedSize: 0.2` (the whole position).
    - It filled at the trigger price exactly, 81.54, while `orderPrice: 77.49`
      is Bybit's own slippage bound for the market order.
    - The fee is charged in USDT at `0.00055` taker, as for any close.
    - Order history shows the stop `Filled`. Afterwards there was no resting
      stop, and the position reported `stopLoss: ''`.
    - The accounting closes exactly. The price moved −0.01 and the fees were
      0.0089749 + 0.0089694, which makes −0.0279443, the balance difference to
      the eighth decimal.
  - *Design finding:* setting the stop is a second call after the opening
    fills. That leaves the position unprotected for about a second, and with no
    stop at all if that call fails. Bybit's order creation accepts `stopLoss`
    on the opening order itself. Verify it next: one atomic call is the right
    shape for D1.
  - *Run 3, Bybit, 2026-11-12, `--mode close-first`:* a SOLUSDT LONG of 0.2 at
    81.45, with the stop at 81.32, then a reduce-only market close as a
    strategy's signal would send it. Once the position closed, the stop was
    GONE: no resting stop order, and the position reported `stopLoss: ''`.
    Bybit removes a Full-mode stop with its position, so a normal close leaves
    nothing behind to cancel. The accounting closes exactly: price −0.002 and
    fees 0.0089595 + 0.0089584 make −0.0199179, the balance difference.
  - Still open:
    - `--mode cancel` on its own, to see that `stopLoss: "0"` removes the
      stop while the position stays open (useful when an author changes the
      level, if that ever moves stops already placed);
    - the stop attached to the opening order itself;
    - the same questions on Binance.
- [ ] SS.2 Specs and tasks for the chosen layers.

## Log

- L1 (owner, 2026-11-12): "Si un autor deshabilita su estrategia, y además
  altera o desactiva su alerta de tradingview, qué medida de seguridad hay para
  un suscriptor?"
- L2 Correction, the same day: the assistant had said `Leave` closes the
  subscriber's position. It does not (`leave.py:16`). No in-app close exists
  for a subscriber.
- L3 (owner, 2026-11-12): "Si, va a haber que planificar medidas de seguridad
  para los suscriptores. Un cierre manual no puede ser la única medida de
  seguridad. Un usuario que no entra al panel no puede cerrar a mano."
