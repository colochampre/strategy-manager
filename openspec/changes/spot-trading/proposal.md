# Spot trading

Not planned yet: a placeholder so the requirement is not lost.

Owner, 2026-11-12: "en un futuro, asi como el adapter de Pionex soporta spot,
también lo deben hacer los adapters de Binance, Pionex, y los exchanges a los
que le demos soporte". *Read as:* Bybit, Binance and every exchange supported
later get a spot adapter beside their futures one. Pionex already has one
(`execution/infrastructure/pionex_exchange.py`, not registered).

What is already known and constrains it:

- **Safety (D9 of `subscriber-safety`):** the exchange stop binds futures. A
  spot purchase has no leverage and cannot be liquidated. Which safety
  measures a spot venue requires is decided here, when one is registered.
- **Bybit has one USDT pool (CLAUDE.md, rule 5).** Its Unified Trading Account
  backs spot and linear perpetuals with the same balance. Configuring both
  `spot/USDT` and `usdt-m/USDT` there would let the same money be reserved
  twice. So Bybit spot shares the futures pool and does not get a second one.
- **Binance segregates.** Spot and USDⓈ-M are separate wallets, as on Pionex,
  so Binance spot would be a pool of its own.
- **Fees in kind.** On Pionex spot, a BUY's fee was taken in the base coin and
  shrank the holding. That is the defect that once stranded a position
  (CLAUDE.md, the first round trip). Each new spot venue needs that read live
  before a close is sized from the ledger.
- **Keys.** A spot venue on an exchange needs no second key: one key per user
  and exchange signs everything. The key inspector must report the spot
  trading permission too.
