from decimal import Decimal

import pytest

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency
from strategy_manager.shared.infrastructure.usd_rate import FixedUsdRateProvider


async def test_fixed_usd_rate_provider_returns_the_configured_rate() -> None:
    provider = FixedUsdRateProvider(rates={Currency.BTC: Decimal("50000")})

    rate = await provider.usd_rate(Currency.BTC)

    assert rate == Decimal("50000")


async def test_fixed_usd_rate_provider_returns_a_different_rate_for_another_currency() -> None:
    provider = FixedUsdRateProvider(
        rates={Currency.BTC: Decimal("50000"), Currency.ETH: Decimal("3000")}
    )

    assert await provider.usd_rate(Currency.ETH) == Decimal("3000")


async def test_fixed_usd_rate_provider_rejects_unconfigured_currency() -> None:
    provider = FixedUsdRateProvider(rates={Currency.BTC: Decimal("50000")})

    with pytest.raises(InvariantViolation):
        await provider.usd_rate(Currency.USDT)
