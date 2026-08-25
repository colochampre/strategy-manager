"""Manual check: does the futures POST path work, against an EMPTY wallet?

This is NOT a test. It needs real API credentials, it writes to the live
account, and it genuinely attempts to place an order (CLAUDE.md rule 1: no
test may require a real API credential).

**Nothing can be spent, and that is the whole design.** The futures wallet is
empty, so a correctly-formed order cannot fill -- the venue refuses it for
want of margin. That refusal is the most informative thing available for free:

  - it proves the POST is SIGNED correctly on /uapi/v1/ (a signature failure
    answers differently, and the spot adapter's first live order proved this
    exact point by being refused for permissions rather than for shape)
  - it proves the venue PARSES the payload -- ``type: MARKET_QTY``, ``size``,
    ``reduceOnly``, no ``positionSide`` -- because a malformed field is
    refused before the balance is ever consulted
  - it reveals the real insufficient-margin CODE, which decides whether
    ``PionexFuturesExchangeAdapter`` classifies it as a definitive rejection
    (release the reservation) or as unknown (retry). Guessing that wrong is
    how capital behind a live position gets released.

**The guard is not advisory.** This refuses to run if the futures wallet holds
anything at all, or if any position is open. With funds present the order
could FILL, and that is a different decision belonging to a human who has
chosen the size -- not to a probe whose safety argument is that there is
nothing to spend.

The order is built through the real adapter, not hand-rolled, so what reaches
the venue is what production would send.

Usage:
    cd backend
    uv run python scripts/check_pionex_futures_order.py
    uv run python scripts/check_pionex_futures_order.py --symbol ETH_USDT_PERP
"""

import argparse
import asyncio
import sys
from decimal import Decimal
from uuid import uuid4

from probe_credentials import announce, vault_credentials

from strategy_manager.execution.application.ports import ExchangeError, OpenOrderSpec
from strategy_manager.execution.domain.futures_order import FuturesMarketOrder
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.pionex_futures_exchange import (
    PionexFuturesExchangeAdapter,
    _is_definitive_rejection,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError
from strategy_manager.shared.infrastructure.pionex.factory import (
    futures_read_only_client,
    futures_trade_client,
    read_only_client,
)
from strategy_manager.shared.infrastructure.pionex.signer import PionexCredentials

DEFAULT_SYMBOL = "BTC_USDT_PERP"

# Small enough to stay near the contract minimum across any plausible price,
# large enough that the size does not round away to nothing. It buys nothing
# either way: the wallet is empty.
GRANTED = Decimal("5")
REFERENCE_PRICE = Decimal("64000")


async def _assert_nothing_at_stake(
    settings: object, credentials: PionexCredentials
) -> None:
    """The safety argument in code.

    This probe is safe because there is nothing to spend. If that stops being
    true it is not a safe probe any more, and no amount of intent makes it
    one.
    """
    # The futures WALLET is reported by the balances endpoint the spot read
    # client owns; the futures read client owns positions. Both are needed to
    # say "nothing at stake" honestly.
    async with read_only_client(settings, credentials) as balances_reader:  # type: ignore[arg-type]
        balances = await balances_reader.futures_balances()
        funded = [b for b in balances if b.free or b.frozen]
        if funded:
            held = ", ".join(f"{b.coin} free={b.free} frozen={b.frozen}" for b in funded)
            raise SystemExit(
                f"REFUSING: the futures wallet holds funds ({held}). This probe's "
                "only safety argument is that an order cannot fill. With margin "
                "available it CAN fill, and choosing that size is a decision for "
                "you, not for a script."
            )

    async with futures_read_only_client(settings, credentials) as reader:  # type: ignore[arg-type]
        positions = await reader.positions()
        if positions:
            open_positions = ", ".join(f"{p.symbol} {p.net_size}" for p in positions)
            raise SystemExit(
                f"REFUSING: the futures account holds open positions "
                f"({open_positions}). A new order could interact with them."
            )

    print("futures wallet empty, no open positions: an order cannot fill")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    args = parser.parse_args()

    settings = get_settings()
    print(f"Pionex base URL: {settings.pionex_base_url}")
    print(f"Symbol: {args.symbol}")
    print("This probe DOES send an order. It cannot fill: the wallet is empty.\n")

    async with vault_credentials(settings) as credentials:
        announce(credentials, "vault")
        await _assert_nothing_at_stake(settings, credentials)

        async with futures_trade_client(settings, credentials) as client:
            adapter = PionexFuturesExchangeAdapter(client)

            client_order_id = str(uuid4())
            try:
                order = await adapter.build_open_order(
                    OpenOrderSpec(
                        client_order_id=client_order_id,
                        symbol=args.symbol,
                        side=OrderSide.BUY,
                        granted=GRANTED,
                        price=REFERENCE_PRICE,
                    )
                )
            except (ExchangeError, PionexApiError) as exc:
                print(f"\nBUILD REFUSED -- {exc}")
                print("Nothing was sent.")
                return 1

            assert isinstance(order, FuturesMarketOrder)
            print("\nORDER BUILT BY THE REAL ADAPTER")
            print(f"  symbol        {order.symbol}")
            print(f"  side          {order.side.value}")
            print(f"  size          {order.base_size} (base)")
            print(f"  leverage      {order.leverage}x")
            print(f"  reduceOnly    {order.reduce_only}")
            print(f"  clientOrderId {client_order_id}")

            print("\nSENDING...")
            try:
                placed = await adapter.place(order)
            except ExchangeError as exc:
                print("REFUSED, definitively.")
                print(f"  {exc}")
                _explain(exc.__cause__)
                return 0
            except PionexApiError as exc:
                print("FAILED, ambiguously -- the adapter would RETRY this.")
                print(f"  code={exc.code!r} http={exc.http_status!r}: {exc}")
                print(
                    "\n  If this is really an insufficient-margin refusal, the "
                    "classification is\n  WRONG: a definitive rejection read as "
                    "ambiguous retries forever."
                )
                return 1

    print("ACCEPTED -- an order was created.")
    print(f"  exchange_order_id {placed.exchange_order_id}")
    print(
        "\n  This was NOT expected against an empty wallet. Check the account "
        "now: an\n  order may be resting at the venue."
    )
    return 1


# Codes observed live. VERIFIED 2026-08-25 against the owner's account.
#
# TRADE_TYPE_DENIED is an ELIGIBILITY gate, not a margin refusal, and the
# difference matters: it is decided before the order's fields or the wallet
# balance are ever consulted, so a run ending here proves the request was
# signed and authenticated and NOTHING about whether the payload is valid.
ELIGIBILITY_CODES = frozenset({"TRADE_TYPE_DENIED"})

_ELIGIBILITY = """
  This is an ELIGIBILITY refusal, not a margin one.
  Futures trading is not permitted for this key or this account.

  PROVEN: the POST is signed and authenticated on /uapi/v1/. A bad signature,
  or a key without futures access, answers AUTH_UNAVAILABLE instead -- which
  is exactly what the environment's read-only key gave for the settings write.

  NOT PROVEN: that the venue accepts this payload. The gate is reached before
  the order's fields are validated, so MARKET_QTY, size and reduceOnly remain
  unexercised. Do not record them as verified on the strength of this run.

  NEXT: enable futures/perpetual trading on the account and grant the API key
  that permission, then run this again. Funding the wallet first changes
  nothing -- this refusal happens before the balance is consulted.
"""

_DEFINITIVE = """
  Definitive means the venue saw the order and said no, so PlaceOrder may
  release the reservation rather than retry.

  If this refusal is about MARGIN, it also proves the venue parsed MARKET_QTY,
  size and reduceOnly: a malformed field is refused before the balance is ever
  consulted. Read the message to tell which of the two it was.
"""


def _explain(cause: BaseException | None) -> None:
    if not isinstance(cause, PionexApiError):
        return
    print(f"  code={cause.code!r} http={cause.http_status!r}")
    print(f"  classified definitive: {_is_definitive_rejection(cause)}")
    print(_ELIGIBILITY if cause.code in ELIGIBILITY_CODES else _DEFINITIVE)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
