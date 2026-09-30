"""The answers behind ``TradeCapabilityPort``: can this exchange's active key
trade? (decisions 18, 20 and 30; design.md § 4a).

``ProcessSignalHandler`` asks before an OPENING signal reaches the Existing-
Position Guard, the balance refresh and the pool's advisory lock, so the answer
has to be cheap, local and free of secrets:

- ``VaultTradeCapabilityAdapter`` reads the ``trade_capable`` column of the
  exchange's ACTIVE row, recorded when the key was saved, and NOTHING ELSE. It
  selects no ciphertext, no nonce and no wrapped key, and it has no cipher to
  decrypt with (rule 8: plaintext exists only in the worker at signing time).
  It does not look at how the fact was established either: a Binance key whose
  capability the owner confirmed answers ``TRADE_CAPABLE``, because the owner
  has vouched for it and the venue is the backstop (decision 30).
- ``DryRunTradeCapability`` answers ``TRADE_CAPABLE`` for everything. Under
  ``DRY_RUN`` the fake exchange places nothing, so no key is needed and none
  can be missing; wiring it is a ``DRY_RUN`` decision made in ``main.py``
  beside the exchange adapters.

No lock, no cache and no venue call: a key deleted or replaced a moment ago is
seen on the very next signal. A key replaced between this read and
``PlaceOrder`` fails at the venue as before (the accepted residual race).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.models import ExchangeCredentialRow
from strategy_manager.signals.application.ports import TradeCapability

_ROW = ExchangeCredentialRow


class VaultTradeCapabilityAdapter:
    """One indexed read of ``exchange_credentials (trade_capable)`` for the
    exchange's active row. The partial unique index
    ``ux_exchange_credentials_one_active_per_exchange`` guarantees at most one
    such row, so the answer is never ambiguous."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def capability(self, exchange: str) -> TradeCapability:
        trade_capable = (
            await self._session.execute(
                select(_ROW.trade_capable).where(_ROW.exchange == exchange, _ROW.is_active)
            )
        ).scalar_one_or_none()
        if trade_capable is None:
            return TradeCapability.NO_KEY
        return TradeCapability.TRADE_CAPABLE if trade_capable else TradeCapability.READ_ONLY


class DryRunTradeCapability:
    """Always ``TRADE_CAPABLE``: a rehearsal refuses no exchange for its key."""

    async def capability(self, exchange: str) -> TradeCapability:
        return TradeCapability.TRADE_CAPABLE
