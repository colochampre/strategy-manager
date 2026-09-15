"""Binance REST adapter.

The third venue, added for a strategy that trades three Binance pairs at once.

Binance segregates wallets the way Pionex does and Bybit's unified account does
not: spot, USDⓈ-M futures, COIN-M futures, cross and isolated margin and
funding are separate balances moved between by universal transfer (verified
against Binance's documentation 2026-09-15). So each wallet is its own pool.

Futures and account-wide wallet reads live on different hosts --
``fapi.binance.com`` and ``api.binance.com`` -- but share one signing scheme.

Started, as every venue here is, with a read-only probe
(``scripts/check_binance_read.py``) before any adapter is designed on top of
what the documentation claims.
"""

EXCHANGE = "binance"
