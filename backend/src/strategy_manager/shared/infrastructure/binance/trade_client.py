"""Order submission and fill lookup against the Binance USDⓈ-M futures API.

The sibling of ``read_client.py``, and the class that CAN move money. Its
read-only twin exists so that everything which only looks at the account never
has to hold one of these -- and this one composes that one rather than
duplicating its parsing, because reading is a strict subset of what it needs.

**Fills take two hops here, not one.** Bybit's execution endpoint accepts
``orderLinkId`` directly, so the id this system chose before it ever spoke to
the exchange settles the order. Binance's ``/fapi/v1/userTrades`` accepts
``symbol`` and ``orderId`` only -- ``origClientOrderId`` is not among its
parameters -- so settlement is ``newClientOrderId -> orderId -> fills``, the
same shape Pionex forced. The lookup hop is therefore not optional plumbing:
it is the only bridge between our own handle and the venue's.

**The account must be in one-way mode**, and that is asserted before any order
is sent, not discovered from a rejection. Binance would fail on its own --
``reduceOnly`` cannot be sent in hedge mode and ``positionSide`` becomes
mandatory -- but a numeric venue code is a far worse operator message than
naming the cause, and in hedge mode a symbol holds a long AND a short at once,
so a close that silently opened a position on the other side is exactly the
failure this project refuses before the fact.

``positionSide`` is deliberately never sent: omitting it is what pins one-way
mode, since Binance defaults it to ``BOTH`` there and requires it only when the
account is hedged -- which this client has already refused.

**Failures are sorted into definitive and ambiguous.** A definitive rejection
read as ambiguous merely retries; an ambiguous failure read as definitive
releases the capital behind a position that may well be open. Only ``-2013``
means "no such order".

**No retries anywhere.** One timeout, set on the ``httpx`` client in
``factory.py``. A call that outlived ``recvWindow`` cannot succeed on a retry,
because the signature it carries is already stale -- and retrying an order
whose outcome is unknown is how one signal becomes two positions. Retry is the
job queue's decision, made with the ledger in view.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Final

import httpx

from strategy_manager.shared.infrastructure.binance.errors import (
    BinanceApiError,
    BinanceOrderNotFound,
)
from strategy_manager.shared.infrastructure.binance.read_client import (
    BinanceReadOnlyClient,
    PerpContract,
    parse_contract,
)
from strategy_manager.shared.infrastructure.binance.signer import BinanceSigner
from strategy_manager.shared.infrastructure.binance.transport import BinanceTransport

# One path serves both verbs: POST places an order, GET looks one up.
ORDER_PATH = "/fapi/v1/order"
USER_TRADES_PATH = "/fapi/v1/userTrades"
POSITION_MODE_PATH = "/fapi/v1/positionSide/dual"

MARKET = "MARKET"

# Binance documents newClientOrderId as ^[\.A-Z\:/a-z0-9_-]{1,36}$. A UUID4 is
# exactly 36 characters and matches, so it fits with nothing to spare. Checked
# rather than assumed: the client order id is the only handle that makes an
# in-flight order recoverable after a crash, and the day someone prefixes it
# for readability is the day orders stop being recoverable.
CLIENT_ORDER_ID_MAX_LENGTH: Final = 36
_CLIENT_ORDER_ID_PATTERN: Final = re.compile(r"[\.A-Z\:/a-z0-9_-]+")

# Binance's own code for a lookup that found nothing.
ORDER_NOT_FOUND_CODES: Final = frozenset(
    {
        "-2013",  # Order does not exist.
    }
)

# Codes that mean Binance did NOT tell us what happened to the order. Both are
# verbatim admissions that the outcome is unknown, so neither may ever be
# reported as a decision the exchange made.
AMBIGUOUS_CODES: Final = frozenset(
    {
        "-1001",  # DISCONNECTED: internal error, unable to process the request
        "-1007",  # TIMEOUT: "Send status unknown; execution status unknown."
    }
)

# Everything else negative is a decision Binance made about this request and is
# definitive: -1021 (timestamp outside recvWindow), -1022 (bad signature),
# -1008 (server busy / throttled), -2010 (order rejected), -2014 (malformed key),
# -4164 (below the minimum notional), -4131 (percent-price ceiling).
#
# -2015 is "Invalid API-key, IP, or permissions for action" -- ONE code for
# three different causes. The trade key is IP-restricted, so the day the worker
# moves to another host this is the code it will answer with, while the
# read-only .env key keeps working from anywhere and makes the account look
# fine. Read it as an allowlist question first, not as a revoked key.


@dataclass(frozen=True, slots=True)
class BinanceOrderAck:
    """What Binance returns when it accepts an order: ids, and nothing this
    system can settle from."""

    order_id: int
    client_order_id: str


@dataclass(frozen=True, slots=True)
class BinanceExecution:
    """One fill, a straight transcription of the wire payload.

    ``commission`` is charged in ``commission_asset``, which on a USDⓈ-M
    contract is USDT on BOTH sides -- never in the base coin. That is what
    makes a close sized from the ledger equal its open exactly, and it is the
    opposite of Pionex spot, where a buy's fee came out of the holding.
    """

    trade_id: int
    order_id: int
    symbol: str
    side: str
    price: Decimal
    qty: Decimal
    commission: Decimal
    commission_asset: str
    trade_time_ms: int


class BinancePerpCatalog:
    """Fetches the contract table once and answers from memory.

    Binance offers no per-symbol variant of ``exchangeInfo``: every question
    about one market downloads all 897. Cached per instance, and the trade
    client is built per job, so this costs one GET on a job that is about to
    place an order. That is the right trade for numbers that decide whether the
    order is accepted at all -- a stale cached step produces a rejection nobody
    can explain from the logs.

    Entries are parsed on demand rather than up front, which is where this
    departs from its Bybit twin: the payload mixes perpetuals, dated
    quarterlies and 191 ``TRADIFI_PERPETUAL`` contracts, and parsing all of
    them to answer about one would let an unrelated market's shape change
    refuse every order on this venue.
    """

    def __init__(self, reader: BinanceReadOnlyClient) -> None:
        self._reader = reader
        self._entries: dict[str, Any] | None = None

    async def rules_for(self, symbol: str) -> PerpContract:
        if self._entries is None:
            self._entries = {
                str(entry.get("symbol", "")).upper(): entry
                for entry in await self._reader.perp_catalogue()
                if isinstance(entry, dict)
            }

        entry = self._entries.get(symbol.upper())
        if entry is None:
            raise BinanceApiError(
                f"Binance does not list {symbol!r} as a USDⓈ-M futures contract"
            )
        return parse_contract(entry)


class BinanceTradeClient:
    """Signed access to the Binance USDⓈ-M futures trade endpoints. This class
    CAN move money."""

    def __init__(self, http: httpx.AsyncClient, signer: BinanceSigner) -> None:
        self._transport = BinanceTransport(http, signer)
        self._read = BinanceReadOnlyClient(http, signer)
        self._symbols = BinancePerpCatalog(self._read)
        self._hedged: bool | None = None

    async def perp_rules(self, symbol: str) -> PerpContract:
        """The step, minimums and contract type this market imposes."""
        return await self._symbols.rules_for(symbol)

    async def leverage_for(self, symbol: str) -> Decimal:
        """The leverage this symbol is configured at, which is what sizes an
        opening order.

        Read rather than assumed, and never defaulted: a default would silently
        size a position at the wrong multiple of the capital the allocation
        engine granted.
        """
        return await self._read.leverage_for(symbol)

    async def assert_one_way_mode(self) -> None:
        """Refuses a hedged account before any order is sent.

        Cached after the first read: position mode is an account-wide setting,
        the client is built per job, and re-reading it on every order would add
        a round trip to the hot path for a number that cannot change inside one
        job.
        """
        if self._hedged is None:
            payload = await self._transport.get_signed(POSITION_MODE_PATH)
            if not isinstance(payload, dict):
                raise BinanceApiError(
                    f"{POSITION_MODE_PATH} returned a non-object body"
                )
            dual = payload.get("dualSidePosition")
            if not isinstance(dual, bool):
                raise BinanceApiError(
                    "dualSidePosition must be a boolean, got "
                    f"{type(dual).__name__}; the position mode is unknown and "
                    "no order may be sent against an unknown mode"
                )
            self._hedged = dual

        if self._hedged:
            raise BinanceApiError(
                "the futures account is in hedge mode (dualSidePosition is "
                "true); this adapter is written for one-way mode only. In hedge "
                "mode a symbol holds a long and a short at once, positionSide "
                "becomes required on every order, and reduceOnly stops "
                "protecting a close"
            )

    async def place_market_order(
        self,
        *,
        symbol: str,
        client_order_id: str,
        side: str,
        qty: Decimal,
        reduce_only: bool,
    ) -> BinanceOrderAck:
        """Places a MARKET order for ``qty`` of the base asset.

        ``reduceOnly`` is sent explicitly on both an open and a close rather
        than left to its default, so the wire says which one this is. It cannot
        be sent in hedge mode at all, which is why the mode is asserted first.

        The local checks run before the mode read: an id this system built
        wrongly is our bug, and it costs nothing to refuse it without touching
        the network.
        """
        _assert_valid_client_order_id(client_order_id)
        if qty <= 0:
            raise BinanceApiError(f"qty must be positive, got {qty}")

        await self.assert_one_way_mode()

        params = {
            "symbol": symbol,
            "side": side,
            "type": MARKET,
            "quantity": _plain(qty),
            "newClientOrderId": client_order_id,
            # A string enum here, not a JSON boolean: Binance documents
            # "true"/"false".
            "reduceOnly": "true" if reduce_only else "false",
        }
        data = await self._transport.post(ORDER_PATH, params)

        if not isinstance(data, dict):
            raise BinanceApiError("new order returned no result object")

        order_id = data.get("orderId")
        if isinstance(order_id, bool) or not isinstance(order_id, int):
            raise BinanceApiError(
                f"new order returned no orderId, got {order_id!r}; without it "
                "the fills for this order cannot be read back"
            )

        # Binance echoes the client order id back. If it ever echoes a different
        # one, the handle this system uses to recover the order does not name
        # the order Binance actually created, and settlement would go looking
        # for something that is not there.
        echoed = data.get("clientOrderId")
        if echoed and str(echoed) != client_order_id:
            raise BinanceApiError(
                f"Binance echoed client order id {echoed!r} for an order placed "
                f"as {client_order_id!r}; the order cannot be tracked by our own id"
            )

        return BinanceOrderAck(order_id=order_id, client_order_id=client_order_id)

    async def order_id_for(self, client_order_id: str, symbol: str) -> int:
        """Resolves our own id into Binance's, hop one of two.

        ``symbol`` is mandatory on this endpoint: Binance scopes an order
        lookup to one market, so the id alone cannot find it.

        Raises ``BinanceOrderNotFound`` only when Binance positively reports no
        such order. Every other failure propagates as ``BinanceApiError`` with
        its code intact, so the caller can tell a definitive rejection from an
        outcome nobody knows yet.
        """
        try:
            data = await self._transport.get_signed(
                ORDER_PATH, {"symbol": symbol, "origClientOrderId": client_order_id}
            )
        except BinanceApiError as exc:
            if exc.code in ORDER_NOT_FOUND_CODES:
                raise BinanceOrderNotFound(
                    f"Binance has no {symbol} order under client order id "
                    f"{client_order_id}"
                ) from exc
            raise

        if not isinstance(data, dict):
            raise BinanceApiError(
                f"the {symbol} order lookup returned no result object"
            )
        return _integer(data, "orderId")

    async def assert_order_placed(self, client_order_id: str, symbol: str) -> None:
        """Raises ``BinanceOrderNotFound`` only when Binance positively reports
        no such order."""
        await self.order_id_for(client_order_id, symbol)

    async def fills_for(self, *, symbol: str, order_id: int) -> list[BinanceExecution]:
        """Every fill for one EXCHANGE order id, hop two of two.

        ``symbol`` is mandatory, and ``orderId`` is documented as usable only
        together with it. An empty list is a legitimate transient state --
        accepted but not yet published -- and is NOT evidence that the order
        does not exist. Ask ``assert_order_placed`` for that.
        """
        payload = await self._transport.get_signed(
            USER_TRADES_PATH, {"symbol": symbol, "orderId": str(order_id)}
        )
        if not isinstance(payload, list):
            raise BinanceApiError(
                f"{USER_TRADES_PATH} did not return a list, got "
                f"{type(payload).__name__}"
            )
        return [_parse_execution(entry) for entry in payload]


def _plain(value: Decimal) -> str:
    """Formats a ``Decimal`` without scientific notation.

    ``str(Decimal("1E-8"))`` is ``'1E-8'``, and a size that came out of a
    division very much can carry that exponent. A futures size is ALWAYS a
    quotient (``granted * leverage / price``), so this is on the hot path
    rather than an edge case.
    """
    return format(value.normalize(), "f")


def _assert_valid_client_order_id(client_order_id: str) -> None:
    if not client_order_id or len(client_order_id) > CLIENT_ORDER_ID_MAX_LENGTH:
        raise BinanceApiError(
            f"newClientOrderId must be 1-{CLIENT_ORDER_ID_MAX_LENGTH} characters, "
            f"got {len(client_order_id)}. A UUID4 is exactly "
            f"{CLIENT_ORDER_ID_MAX_LENGTH}, so there is no room for a prefix."
        )
    if not _CLIENT_ORDER_ID_PATTERN.fullmatch(client_order_id):
        raise BinanceApiError(
            "newClientOrderId must contain only letters, numbers, dots, colons, "
            f"slashes, dashes and underscores, got {client_order_id!r}"
        )


def _parse_execution(entry: Any) -> BinanceExecution:
    fields = _object(entry, "userTrade")
    return BinanceExecution(
        trade_id=_integer(fields, "id"),
        order_id=_integer(fields, "orderId"),
        symbol=_text(fields, "symbol"),
        side=_text(fields, "side"),
        price=_amount(fields, "price"),
        qty=_amount(fields, "qty"),
        commission=_amount(fields, "commission"),
        commission_asset=_text(fields, "commissionAsset"),
        trade_time_ms=_millis(fields, "time"),
    )


def _object(entry: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(entry, dict):
        raise BinanceApiError(f"{label} is not an object, got {type(entry).__name__}")
    return entry


def _text(fields: Mapping[str, Any], field: str) -> str:
    value = fields.get(field)
    if not isinstance(value, str) or not value:
        raise BinanceApiError(f"{field} must be a non-empty string, got {value!r}")
    return value


def _integer(fields: Mapping[str, Any], field: str) -> int:
    """Trade and order ids arrive as JSON INTEGERS here, where Bybit sends
    strings. ``bool`` is rejected explicitly because it passes
    ``isinstance(x, int)`` and would read as the id 0 or 1."""
    value = fields.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BinanceApiError(
            f"{field} must be an integer id, got {type(value).__name__}"
        )
    return value


def _amount(fields: Mapping[str, Any], field: str) -> Decimal:
    """Binance sends money as decimal STRINGS, and this keeps it that way.

    A JSON number has already lost precision before it reaches this process, so
    it is rejected rather than coerced, and an empty or missing field is
    refused rather than read as zero. This is a fill price or a fee: it lands
    in the append-only ledger and can never be corrected there.
    """
    value = fields.get(field)
    if not isinstance(value, str) or not value:
        raise BinanceApiError(
            f"{field} must be a non-empty string amount, got {value!r}"
        )
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise BinanceApiError(f"{field} is not a valid decimal: {value!r}") from exc


def _millis(fields: Mapping[str, Any], field: str) -> int:
    """Binance sends trade timestamps as integer milliseconds.

    Parsed with ``int`` and never ``float``: a float would round a millisecond
    that orders two fills of the same order. A ``bool`` is rejected for the
    same reason it is on an id.
    """
    value = fields.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BinanceApiError(
            f"{field} must be a millisecond timestamp, got {type(value).__name__}"
        )
    return value
