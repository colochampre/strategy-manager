"""Perpetual contract rules and the rounding they force.

Every number here decides whether an order is accepted at all. The spot
equivalent went unenforced at first and would have rejected every order on
both legs.
"""

from decimal import Decimal
from typing import Any

import httpx
import pytest

from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError
from strategy_manager.shared.infrastructure.pionex.perp_symbols import (
    SYMBOLS_PATH,
    PerpRules,
    PionexPerpCatalog,
)
from strategy_manager.shared.infrastructure.pionex.signer import PionexSigner
from strategy_manager.shared.infrastructure.pionex.transport import PionexTransport

# BTC_USDT_PERP exactly as the live account reported it on 2026-08-24.
BTC_PERP: dict[str, Any] = {
    "symbol": "BTC_USDT_PERP",
    "type": "PERP",
    "baseCurrency": "BTC",
    "quoteCurrency": "USDT",
    "basePrecision": 4,
    "quotePrecision": 1,
    "minNotional": "1",
    "baseStep": "0.0001",
    "quoteStep": "0.1",
    "minSizeMarket": "0.0001",
    "maxSizeMarket": "100",
    "status": "TRADING",
}


def _rules(**overrides: Any) -> PerpRules:
    entry = {**BTC_PERP, **overrides}
    return PerpRules(
        symbol=str(entry["symbol"]),
        base_precision=int(entry["basePrecision"]),
        base_step=Decimal(str(entry["baseStep"])),
        min_notional=Decimal(str(entry["minNotional"])),
        min_size_market=Decimal(str(entry["minSizeMarket"])),
        max_size_market=Decimal(str(entry["maxSizeMarket"])),
        status=str(entry["status"]),
    )


def _catalog(
    signer: PionexSigner,
    response: httpx.Response,
    recorded: list[httpx.Request],
) -> PionexPerpCatalog:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return response

    http = httpx.AsyncClient(
        base_url="https://api.pionex.com",
        transport=httpx.MockTransport(handler),
    )
    return PionexPerpCatalog(PionexTransport(http, signer))


@pytest.fixture
def recorded() -> list[httpx.Request]:
    return []


def test_a_size_is_truncated_down_to_the_step() -> None:
    """A futures size is always a quotient, so it essentially never lands on
    a step boundary by itself."""
    rules = _rules()

    assert rules.round_base_size(Decimal("0.00789123")) == Decimal("0.0078")


def test_rounding_is_never_upward() -> None:
    """Up spends capital the allocation engine never granted, and on a close
    asks the venue to reduce more than the position holds."""
    rules = _rules()

    for raw in ("0.00019999", "0.0001", "1.99999999"):
        rounded = rules.round_base_size(Decimal(raw))
        assert rounded <= Decimal(raw)


def test_the_step_is_enforced_even_when_the_precision_would_allow_it() -> None:
    """``basePrecision`` and ``baseStep`` agree on every contract observed so
    far, but they are not the same rule. A step of 0.0005 passes a check at
    four decimals and is still rejected by the venue."""
    rules = _rules(baseStep="0.0005", basePrecision=4)

    assert rules.round_base_size(Decimal("0.0007")) == Decimal("0.0005")


def test_a_zero_step_degrades_to_the_declared_precision() -> None:
    """A malformed step must not raise DivisionByZero from inside an order
    path -- the weaker check is still a check."""
    rules = _rules(baseStep="0", basePrecision=3)

    assert rules.round_base_size(Decimal("1.23456")) == Decimal("1.234")


def test_a_size_below_the_market_minimum_is_refused_with_both_numbers() -> None:
    rules = _rules()

    with pytest.raises(PionexApiError, match="at least 0.0001"):
        rules.assert_tradable(Decimal("0.00001"), Decimal("64000"))


def test_a_size_above_the_market_maximum_is_refused() -> None:
    """Spot has no ceiling. Futures does, and leverage makes it far easier to
    hit: at 100x a grant a hundredth of the size reaches it."""
    rules = _rules()

    with pytest.raises(PionexApiError, match="caps a market order at 100"):
        rules.assert_tradable(Decimal("101"), Decimal("64000"))


def test_a_notional_below_the_minimum_is_refused() -> None:
    rules = _rules(minNotional="50")

    with pytest.raises(PionexApiError, match="notional of at least 50"):
        rules.assert_tradable(Decimal("0.0004"), Decimal("64000"))


def test_an_offline_market_is_refused_before_anything_else() -> None:
    """The operator's remedy differs from every size problem: a different
    symbol, not a different amount."""
    rules = _rules(status="OFFLINE")

    with pytest.raises(PionexApiError, match="is OFFLINE, not TRADING"):
        rules.assert_tradable(Decimal("0.01"), Decimal("64000"))


def test_a_size_inside_every_limit_passes() -> None:
    _rules().assert_tradable(Decimal("0.0078"), Decimal("64000"))


async def test_the_catalogue_is_read_from_the_spot_path_with_type_perp(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """The perpetual table is NOT under /uapi/v1/. Assuming the futures base
    path here returns a 404 on every lookup."""
    payload = {"result": True, "data": {"symbols": [BTC_PERP]}}
    catalog = _catalog(signer, httpx.Response(200, json=payload), recorded)

    await catalog.rules_for("BTC_USDT_PERP")

    assert recorded[0].url.path == SYMBOLS_PATH
    assert not recorded[0].url.path.startswith("/uapi/")
    assert recorded[0].url.params["type"] == "PERP"


async def test_the_table_is_fetched_once_and_answered_from_memory(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    payload = {"result": True, "data": {"symbols": [BTC_PERP]}}
    catalog = _catalog(signer, httpx.Response(200, json=payload), recorded)

    await catalog.rules_for("BTC_USDT_PERP")
    await catalog.rules_for("BTC_USDT_PERP")

    assert len(recorded) == 1


async def test_an_unlisted_market_is_refused_by_name(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    payload = {"result": True, "data": {"symbols": [BTC_PERP]}}
    catalog = _catalog(signer, httpx.Response(200, json=payload), recorded)

    with pytest.raises(PionexApiError, match="does not list 'DOGE_USDT_PERP'"):
        await catalog.rules_for("DOGE_USDT_PERP")


async def test_a_numeric_step_is_rejected_rather_than_silently_coerced(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    payload = {"result": True, "data": {"symbols": [{**BTC_PERP, "baseStep": 0.0001}]}}
    catalog = _catalog(signer, httpx.Response(200, json=payload), recorded)

    with pytest.raises(PionexApiError, match="must be a string amount"):
        await catalog.rules_for("BTC_USDT_PERP")
