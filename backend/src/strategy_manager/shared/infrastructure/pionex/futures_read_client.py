"""Read-only Pionex USDT-M futures adapter.

GET-only by construction, for the same reason ``read_client.py`` is: the
guarantee that this cannot move money is the absence of the code, not a flag.
Order submission for futures belongs behind
``execution.application.ports.ExchangePort``, not here.

This client exists to answer, against a live account, the questions the
futures execution adapter cannot be designed without. The spot adapter taught
that answering them from the docs is not enough -- per-symbol precision was
absent from the spot docs and would have rejected every order on both legs.
So each read below maps to one decision:

``perp_contracts``      Which markets exist, at what precision, and in which
                        settlement currency. Answers the COIN-M open risk
                        directly: a coin-margined contract would appear here
                        with a non-USDT ``quoteCurrency``, or not at all.
``leverage_tiers``      The maximum leverage per notional band, which is a
                        property of the market rather than of the account.
``positions``           The live position read model -- the shape a REVERSE
                        has to reason about, and the only source for what is
                        actually open at the venue.
``leverage_for``        Whether leverage is readable per symbol at all. The
                        project logged "no leverage endpoint is documented"
                        as an open risk; the docs now document one, and this
                        is how that gets confirmed rather than believed.
``margin_mode_for``     CROSS or ISOLATED. Recorded here as a per-symbol
                        SETTING, which contradicts the earlier note that
                        margin mode is an order parameter. It is not one.
``position_mode``       BUYSELL or OPENCLOSE. This decides whether flipping a
                        position is one order or two, so it is not a detail:
                        it changes what REVERSE means.

Base paths are NOT uniform, and assuming they were would cost a debugging
session. Account and trade endpoints live under ``/uapi/v1/``, but the
contract catalogue and the risk table are served from the SPOT common
namespace ``/api/v1/common/`` with ``type=PERP``. Verified 2026-08-24 against
the published futures API reference.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError
from strategy_manager.shared.infrastructure.pionex.signer import PionexSigner
from strategy_manager.shared.infrastructure.pionex.transport import PionexTransport

# Served from the spot common namespace, not /uapi/v1/. See the module docstring.
SYMBOLS_PATH = "/api/v1/common/symbols"
RISK_TABLE_PATH = "/api/v1/common/riskTable"

POSITIONS_PATH = "/uapi/v1/account/positions"
LEVERAGE_PATH = "/uapi/v1/account/leverage"
POSITION_MODE_PATH = "/uapi/v1/account/positionMode"
MARGIN_MODE_PATH = "/uapi/v1/trade/isolatedMode"

PERP = "PERP"


@dataclass(frozen=True, slots=True)
class PerpContract:
    """One perpetual market's trading rules, as Pionex reports them.

    A transport read model, deliberately a straight transcription of the wire
    payload so that mapping it onto a capital pool stays a separate decision.

    ``quote_currency`` is the field that answers the COIN-M question: a
    USDT-margined contract quotes USDT, a coin-margined one would not.
    """

    symbol: str
    contract_type: str
    base_currency: str
    quote_currency: str
    base_precision: int
    quote_precision: int
    min_notional: Decimal
    base_step: Decimal
    quote_step: Decimal
    min_size_market: Decimal
    max_size_market: Decimal
    status: str

    @property
    def is_usdt_margined(self) -> bool:
        return self.quote_currency.upper() == "USDT"

    @property
    def is_trading(self) -> bool:
        return self.status.upper() == "TRADING"


@dataclass(frozen=True, slots=True)
class LeverageTier:
    """One notional band and the maximum leverage allowed inside it."""

    row_num: int
    notional_limit: Decimal
    max_leverage: Decimal
    maint_margin_ratio: Decimal


@dataclass(frozen=True, slots=True)
class FuturesPosition:
    """One open position exactly as the venue reports it.

    ``net_size`` is signed by direction at the venue for one-way accounts and
    reported alongside ``position_side`` for hedged ones, so both are kept:
    deriving one from the other is the kind of assumption that flips a trade.
    """

    position_id: str
    symbol: str
    position_side: str
    isolated_mode: str
    net_size: Decimal
    avg_price: Decimal
    leverage: Decimal
    unrealized_pnl: Decimal | None
    mark_price: Decimal | None
    liquidation_price: Decimal | None


class PionexFuturesReadClient:
    """Signed, read-only access to Pionex futures market and account state."""

    def __init__(self, http: httpx.AsyncClient, signer: PionexSigner) -> None:
        self._transport = PionexTransport(http, signer)

    async def perp_contracts(self) -> list[PerpContract]:
        """Every perpetual contract Pionex lists, with its trading rules."""
        data = await self._read(SYMBOLS_PATH, {"type": PERP})
        return [_parse_contract(entry) for entry in _list_of(data, "symbols")]

    async def leverage_tiers(self, symbol: str) -> list[LeverageTier]:
        """The risk table for one symbol: notional bands and max leverage."""
        data = await self._read(RISK_TABLE_PATH, {"symbol": symbol})
        for entry in _list_of(data, "symbols"):
            if _text(entry, "symbol").upper() == symbol.upper():
                return [_parse_tier(row) for row in _list_of(entry, "rows")]
        raise PionexApiError(f"the risk table reports no rows for {symbol!r}")

    async def positions(self) -> list[FuturesPosition]:
        """Every position currently open on the futures account."""
        data = await self._read(POSITIONS_PATH)
        return [_parse_position(entry) for entry in _list_of(data, "positions")]

    async def leverage_for(self, symbol: str) -> Decimal:
        """The leverage configured for one symbol."""
        data = await self._read(LEVERAGE_PATH, {"symbol": symbol})
        return _amount(data, "leverage")

    async def margin_mode_for(self, symbol: str) -> str:
        """CROSS or ISOLATED, as configured for one symbol."""
        data = await self._read(MARGIN_MODE_PATH, {"symbol": symbol})
        return _text(data, "isolatedMode")

    async def position_mode(self) -> str:
        """BUYSELL (one-way) or OPENCLOSE (hedged) for the whole account."""
        data = await self._read(POSITION_MODE_PATH)
        return _text(data, "positionMode")

    async def _read(
        self, path: str, params: Mapping[str, str] | None = None
    ) -> Mapping[str, Any]:
        data = await self._transport.get(path, params)
        if not isinstance(data, dict):
            raise PionexApiError(
                f"GET {path} returned no data object, got {type(data).__name__}"
            )
        return data


def _list_of(data: Mapping[str, Any], field: str) -> list[Any]:
    """Reads a list field, naming what actually arrived when it is not one.

    The observed keys are in the message on purpose. This client's whole job
    is finding out where the documented shape and the live shape disagree,
    and "symbols payload is not a list" tells you nothing about which one you
    got instead.
    """
    value = data.get(field)
    if not isinstance(value, list):
        raise PionexApiError(
            f"expected {field!r} to be a list, got {type(value).__name__}; "
            f"payload keys were {sorted(data)}"
        )
    return value


def _parse_contract(entry: Any) -> PerpContract:
    fields = _object(entry, "symbol entry")
    return PerpContract(
        symbol=_text(fields, "symbol").upper(),
        contract_type=_text(fields, "contractType"),
        base_currency=_text(fields, "baseCurrency"),
        quote_currency=_text(fields, "quoteCurrency"),
        base_precision=_integer(fields, "basePrecision"),
        quote_precision=_integer(fields, "quotePrecision"),
        min_notional=_amount(fields, "minNotional"),
        base_step=_amount(fields, "baseStep"),
        quote_step=_amount(fields, "quoteStep"),
        min_size_market=_amount(fields, "minSizeMarket"),
        max_size_market=_amount(fields, "maxSizeMarket"),
        status=_text(fields, "status"),
    )


def _parse_tier(entry: Any) -> LeverageTier:
    fields = _object(entry, "risk table row")
    return LeverageTier(
        row_num=_integer(fields, "rowNum"),
        notional_limit=_amount(fields, "notionalLimit"),
        max_leverage=_amount(fields, "maxLeverage"),
        maint_margin_ratio=_amount(fields, "maintMarginRatio"),
    )


def _parse_position(entry: Any) -> FuturesPosition:
    fields = _object(entry, "position entry")
    return FuturesPosition(
        position_id=str(fields.get("positionId", "")),
        symbol=_text(fields, "symbol").upper(),
        position_side=_text(fields, "positionSide"),
        isolated_mode=_text(fields, "isolatedMode"),
        net_size=_amount(fields, "netSize"),
        avg_price=_amount(fields, "avgPrice"),
        leverage=_amount(fields, "leverage"),
        unrealized_pnl=_optional_amount(fields, "unrealizedPnL"),
        mark_price=_optional_amount(fields, "markPrice"),
        liquidation_price=_optional_amount(fields, "liquidationPrice"),
    )


def _object(entry: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(entry, dict):
        raise PionexApiError(f"{label} is not an object, got {type(entry).__name__}")
    return entry


def _text(fields: Mapping[str, Any], field: str) -> str:
    value = fields.get(field)
    if not isinstance(value, str) or not value:
        raise PionexApiError(
            f"{field} must be a non-empty string, got {value!r}"
        )
    return value


def _integer(fields: Mapping[str, Any], field: str) -> int:
    value = fields.get(field)
    # ``bool`` is an ``int`` subclass, and a precision of ``True`` would sail
    # through every later check as 1.
    if not isinstance(value, int) or isinstance(value, bool):
        raise PionexApiError(
            f"{field} must be an integer, got {type(value).__name__}"
        )
    if value < 0:
        raise PionexApiError(f"{field} must not be negative, got {value}")
    return value


def _amount(fields: Mapping[str, Any], field: str) -> Decimal:
    """Amounts arrive as strings and are parsed exactly.

    A JSON number has already lost precision before it reaches this process,
    so it is rejected rather than coerced. This is the same rule the spot
    balance reader enforces, and for the same reason: this is real money.
    """
    value = fields.get(field)
    if not isinstance(value, str):
        raise PionexApiError(
            f"{field} must be a string amount, got {type(value).__name__}"
        )
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise PionexApiError(f"{field} is not a valid decimal: {value!r}") from exc


def _optional_amount(fields: Mapping[str, Any], field: str) -> Decimal | None:
    """For fields the venue may legitimately omit.

    ``None`` means "not reported", never zero. An unrealized PnL of zero and
    an unreported one are different facts and must not collapse.
    """
    return None if fields.get(field) is None else _amount(fields, field)
