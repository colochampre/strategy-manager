"""Everything ``ExchangePort.place`` can be handed.

Two venue-specific vocabularies under one name, deliberately NOT flattened
into a single four-variant union that any adapter might receive. Spot's
``MarketBuy | MarketSell`` exists to make a wrongly-denominated order
unrepresentable, and a futures ``MARKET_QTY`` does not participate in that
distinction at all -- it is base-sized whichever way it goes.

What keeps them apart is not this alias. It is routing: every adapter declares
the ``venues`` it can trade, the composition root maps venue to adapter, and a
signal for a venue nothing serves is refused before an order is built. This
alias only says what the port's parameter type is once that routing has
already chosen.
"""

from strategy_manager.execution.domain.futures_order import FuturesMarketOrder
from strategy_manager.execution.domain.order import MarketBuy, MarketSell

SpotOrder = MarketBuy | MarketSell
"""What a spot adapter builds and places."""

FuturesOrder = FuturesMarketOrder
"""What a futures adapter builds and places."""

PlaceableOrder = SpotOrder | FuturesOrder
"""What ``ExchangePort.place`` receives, whichever venue routed to it."""
