"""Stand-in ``BalanceSourcePort`` until a real Pionex balance adapter exists
— mirrors the role ``FakeExchangeAdapter`` plays for ``ExchangePort`` in the
design's component inventory.
"""

from decimal import Decimal

from strategy_manager.accounts.application.ports import PoolFunds
from strategy_manager.shared.domain.errors import InvariantViolation


class FakeBalanceSource:
    """In-memory balances, settable per test/dev scenario."""

    def __init__(self, balances: dict[tuple[str, str], Decimal] | None = None) -> None:
        self._funds: dict[tuple[str, str], PoolFunds] = {
            pool: PoolFunds(total=amount, available=amount)
            for pool, amount in (balances or {}).items()
        }

    def set_balance(self, venue: str, settlement_currency: str, balance: Decimal) -> None:
        """A pool with nothing committed: its total and availability agree."""
        self.set_funds(venue, settlement_currency, total=balance, available=balance)

    def set_funds(
        self,
        venue: str,
        settlement_currency: str,
        *,
        total: Decimal,
        available: Decimal,
    ) -> None:
        self._funds[(venue, settlement_currency)] = PoolFunds(total=total, available=available)

    async def read_balance(self, venue: str, settlement_currency: str) -> PoolFunds:
        try:
            return self._funds[(venue, settlement_currency)]
        except KeyError as exc:
            raise InvariantViolation(
                f"no balance configured for ({venue}, {settlement_currency})"
            ) from exc
