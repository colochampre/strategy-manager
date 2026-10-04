"""The taker fee rates the simulated exchange charges (design § E).

Layer: infrastructure/execution. A fact about two venues, read by the
simulated exchange and wired by the composition root.

Why constants and not configuration: a rate changes only when the account's
fee tier does, and that should be a dated, reviewed commit, so that a ledger
row's fee can be explained from history. A setting would live outside the
repository, where a typo silently changes every simulated result.

A simulated fill is a market order, so only TAKER rates belong here. An
exchange with no entry has no simulated exchange at all (``main.py``): a fee of
zero is never charged because a rate is missing.
"""

from decimal import Decimal
from types import MappingProxyType

from strategy_manager.shared.domain.money import Exchange

SIMULATED_TAKER_FEE_RATES = MappingProxyType(
    {
        # Verified. The real round trip of 2026-08-27 was charged this rate on
        # both legs: its fees, 0.05883625 USDT, are exactly 0.00055 x 106.975.
        Exchange.BYBIT.value: Decimal("0.00055"),
        # The OWNER'S FIGURE, read on the account on 2026-10-04. NOT confirmed
        # by a real round trip in this project. The maker rate, 0.02%, is not
        # used: a simulated fill is a market order.
        Exchange.BINANCE.value: Decimal("0.0005"),
    }
)

# The currency every simulated fee is charged in, on both sides. No rate is
# verified for any other (rule 7: a fee is never converted).
SIMULATED_FEE_CURRENCY = "USDT"
