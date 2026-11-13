# Manual trading beside the system

Not planned yet. Comes after `subscriber-safety`.

## The problem

Reconciliation compares every position the venue reports in a pool, not only
the symbols the system traded (`reconciliation/application/scan_pools.py`,
the `symbols` union). A position opened by hand in the same wallet has no
allocation behind it, so it becomes `NO_MATCHING_ALLOCATION` / `NOT_BOOKABLE`,
and `announce_needs_owner` sends it to the operator's Telegram as an ERROR.
Seen on 2026-11-12: the stop probes (`check_bybit_stop.py`,
`check_binance_stop.py`) open outside the system and each paged the owner.
With several users, every manual trade of any user would page the operator.

The alert is the smaller problem. In one-way mode the venue merges positions
on a symbol, so a manual trade on a pair a strategy also trades mixes with
the strategy's: its `reduceOnly` close can close part of the manual position,
or the opening is refused with `LEVERAGE_CONFLICT`.

## What the owner decided (2026-11-12)

- On the alert: "Esa alerta a lo mejor debería ser más discreta y no hacerle
  sonar el telefono si es algo intencional, como el trading manual."
- On sub-accounts: "Olvidate de pionex, si en OKX, BingX, KuCoin y
  Hyperliquid hay subcuenta también, es lo que nos interesa. Subcuenta
  recomendada."

## Proposed scope

1. **A dedicated sub-account is recommended, never required.** The panel says
   so where a key is added: a sub-account keeps manual trading out of the
   system's wallet. A sub-account has its own balance, so capital has to be
   transferred into it.
2. **Reconciliation still reads the whole pool.** It is what finds a real
   orphan the system left behind, and that must keep paging.
3. **The alert is routed by whether the system ever touched the symbol.**
   This is a proposal, not yet decided:
   - a symbol on which the system never held an allocation for that user is
     almost certainly manual: a quiet notice to that user (in the app, no
     push), nothing to the operator;
   - a symbol on which the system held or holds an allocation may be a system
     defect, or a hand on a strategy's pair: it pages as it does today.

The quiet notice is delivered by `notifications`.

## Sub-accounts on the venues of interest (read 2026-11-12, to re-check)

| Venue | Sub-accounts | What was found |
| --- | --- | --- |
| Bybit | yes | main to sub transfers both ways, also over the API; no official limit found |
| Binance | yes | a 2018 FAQ says 5 for a regular user; an institutional doc says no API key on a sub-account without KYC |
| OKX | yes | 5 for a standard user |
| BingX | yes | created from the account menu, API keys per sub-account; one article ties creation to advanced KYC |
| KuCoin | yes | up to 10 API keys per sub-account; futures permission needs futures active on the main account |
| Hyperliquid | yes, gated | the first 10 unlock at 100,000 USD of trading volume |

Hyperliquid's gate means a new user cannot have one there: another reason the
sub-account stays a recommendation.

Sources: Bybit universal transfer
(https://bybit-exchange.github.io/docs/v5/asset/transfer/unitransfer),
Binance sub-account FAQ (https://www.binance.com/hi/support/faq/360020632811),
Binance CaaS FAQ (https://developers.binance.com/en/docs/products/caas/Faq),
OKX (https://docs.tread.fi/connecting-to-exchanges/okx), BingX
(https://bingx.com/en/support/articles/20752636528409), KuCoin
(https://kucoin.com/docs/rest/account/sub-account/add-subaccount-futures-permission),
Hyperliquid (https://hyperliquid.gitbook.io/hyperliquid-docs/trading/sub-accounts).
