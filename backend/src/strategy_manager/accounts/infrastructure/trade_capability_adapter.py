"""The answer behind ``TradeCapabilityPort``: can this exchange's active key
trade? (decisions 18, 20 and 30; design.md § 4a).

``ProcessDelivery`` asks before a LIVE opening reaches the Existing-Position
Guard, the balance refresh and the pool's advisory lock, and ``AllocateCapital``
asks again inside that lock, so the answer has to be cheap, local and free of
secrets. A simulated opening never asks: it places nothing (decision 13).

``VaultTradeCapabilityAdapter`` reads the ``trade_capable`` column of the
exchange's ACTIVE row, recorded when the key was saved, and NOTHING ELSE. It
selects no ciphertext, no nonce and no wrapped key, and it has no cipher to
decrypt with (rule 8: plaintext exists only in the worker at signing time). It
does not look at how the fact was established either: a Binance key whose
capability the owner confirmed answers ``TRADE_CAPABLE``, because the owner has
vouched for it and the venue is the backstop (decision 30).

No lock, no cache and no venue call: a key deleted or replaced a moment ago is
seen on the very next signal. A key replaced between this read and
``PlaceOrder`` fails at the venue as before (the accepted residual race).
"""

from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.models import ExchangeCredentialRow
from strategy_manager.shared.domain.trade_capability import TradeCapability

_ROW = ExchangeCredentialRow


class VaultTradeCapabilityAdapter:
    """One indexed read of ``exchange_credentials (trade_capable)`` for
    ``user_id``'s active row on the exchange: the signal path asks about the
    strategy author's key, and another user's key on the same exchange never
    answers for it (multi-user design AD8). The partial unique index
    ``ux_exchange_credentials_one_active_per_exchange`` on ``(user_id,
    exchange)`` guarantees at most one such row, so the answer is never
    ambiguous."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def capability(self, user_id: UUID, exchange: str) -> TradeCapability:
        trade_capable = (
            await self._session.execute(
                select(_ROW.trade_capable).where(
                    _ROW.user_id == user_id, _ROW.exchange == exchange, _ROW.is_active
                )
            )
        ).scalar_one_or_none()
        if trade_capable is None:
            return TradeCapability.NO_KEY
        return TradeCapability.TRADE_CAPABLE if trade_capable else TradeCapability.READ_ONLY

    async def holds_trade_capable_key(self, user_id: UUID) -> bool:
        """On any exchange: what going live asks (decision 6). The opening asks
        ``capability`` for its own exchange, in the lock."""
        return bool(
            (
                await self._session.execute(
                    select(
                        exists().where(_ROW.user_id == user_id, _ROW.is_active, _ROW.trade_capable)
                    )
                )
            ).scalar_one()
        )
