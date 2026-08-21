"""Read-only Pionex REST adapter.

GET-only by construction: this class has no method that can place, amend or
cancel an order, or move funds. That guarantee is structural rather than a
runtime flag -- ``DRY_RUN`` is not what protects you here, the absence of the
code is. Adding a writing method to this class defeats its only purpose;
order submission belongs behind ``execution.application.ports.ExchangePort``
and lives in ``trade_client.py``.

Note what it holds: a ``PionexTransport``, not an ``httpx.AsyncClient``, and
it only ever calls ``get`` on it. The read-only property survives the shared
transport gaining a ``post``.

Spot and futures are different base paths and are NOT interchangeable
(CLAUDE.md § External constraints): spot lives under ``/api/v1/``, futures
under ``/uapi/v1/``. Paths verified 2026-08-20 against the Pionex API docs.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError
from strategy_manager.shared.infrastructure.pionex.signer import PionexSigner
from strategy_manager.shared.infrastructure.pionex.transport import PionexTransport

SPOT_BALANCES_PATH = "/api/v1/account/balances"
FUTURES_BALANCES_PATH = "/uapi/v1/account/balances"


@dataclass(frozen=True, slots=True)
class CoinBalance:
    """One coin's balance exactly as Pionex reports it.

    This is a transport read model, not a domain object: it is intentionally
    a straight transcription of the wire payload, so that mapping it onto a
    capital pool stays a separate, testable decision.

    ``debts`` exists only on futures balances; spot omits the field entirely,
    which is why ``None`` means "not reported" rather than zero.
    """

    coin: str
    free: Decimal
    frozen: Decimal
    debts: Decimal | None = None


class PionexReadOnlyClient:
    """Signed, read-only access to Pionex account state."""

    def __init__(self, http: httpx.AsyncClient, signer: PionexSigner) -> None:
        self._transport = PionexTransport(http, signer)

    async def spot_balances(self) -> list[CoinBalance]:
        """Trading-account spot balances. Excludes bot and earn balances --
        Pionex does not report those here, which is precisely what makes this
        the number a bot-free account should be sized from.
        """
        return _parse_balances(await self._read(SPOT_BALANCES_PATH))

    async def futures_balances(self) -> list[CoinBalance]:
        """Cross-margin futures wallet balances, including ``debts``."""
        return _parse_balances(await self._read(FUTURES_BALANCES_PATH))

    async def _read(self, path: str) -> Mapping[str, Any]:
        data = await self._transport.get(path)
        if not isinstance(data, dict):
            raise PionexApiError(f"GET {path} returned no data object")
        return data


def _parse_balances(data: Mapping[str, Any]) -> list[CoinBalance]:
    balances = data.get("balances")
    if not isinstance(balances, list):
        raise PionexApiError("balances payload is not a list")
    return [_parse_balance(entry) for entry in balances]


def _parse_balance(entry: Any) -> CoinBalance:
    if not isinstance(entry, dict):
        raise PionexApiError("balance entry is not an object")

    coin = entry.get("coin")
    if not isinstance(coin, str) or not coin:
        raise PionexApiError("balance entry has no coin")

    debts = entry.get("debts")
    return CoinBalance(
        coin=coin,
        free=_to_decimal(entry.get("free"), coin, "free"),
        frozen=_to_decimal(entry.get("frozen"), coin, "frozen"),
        debts=None if debts is None else _to_decimal(debts, coin, "debts"),
    )


def _to_decimal(value: Any, coin: str, field: str) -> Decimal:
    """Pionex sends amounts as strings truncated to 8 decimal places.

    Parsing the string straight into ``Decimal`` keeps it exact. Anything that
    arrives as a JSON number has already lost precision in transit, so it is
    rejected rather than coerced -- this is real money.
    """
    if not isinstance(value, str):
        raise PionexApiError(
            f"{coin}.{field} must be a string amount, got {type(value).__name__}"
        )
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise PionexApiError(f"{coin}.{field} is not a valid decimal: {value!r}") from exc
