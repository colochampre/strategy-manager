"""Stand-in ``BalanceSourcePort`` until a real Pionex balance adapter exists
— mirrors the role ``FakeExchangeAdapter`` plays for ``ExchangePort`` in the
design's component inventory.
"""

from decimal import Decimal

from strategy_manager.shared.domain.errors import InvariantViolation


class FakeBalanceSource:
    """In-memory balances, settable per test/dev scenario."""

    def __init__(self, balances: dict[tuple[str, str], Decimal] | None = None) -> None:
        self._balances: dict[tuple[str, str], Decimal] = dict(balances or {})

    def set_balance(self, venue: str, settlement_currency: str, balance: Decimal) -> None:
        self._balances[(venue, settlement_currency)] = balance

    async def read_balance(self, venue: str, settlement_currency: str) -> Decimal:
        try:
            return self._balances[(venue, settlement_currency)]
        except KeyError as exc:
            raise InvariantViolation(
                f"no balance configured for ({venue}, {settlement_currency})"
            ) from exc
