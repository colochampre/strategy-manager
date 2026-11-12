# Subscriber safety — tasks

Planning. Decisions made; nothing is built until the owner says to build. It goes before `account-deletion`.

## Tasks

- [x] SS.0 Decisions D1-D4 (owner, 2026-11-12), recorded in `proposal.md`.
- [ ] SS.1 Verify the exchange stop live on Bybit and Binance with a probe that
  signs from the vault (`scripts/probe_credentials.py`, `--user-email`): order
  shape, reduce-only, how a stop's fill is reported, and how it is cancelled
  when the strategy closes first.
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
