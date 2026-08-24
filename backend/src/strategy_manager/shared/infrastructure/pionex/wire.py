"""Wire-format rules shared by every Pionex order path.

Small, but neither is cosmetic: one decides whether an order is parseable at
all, and the other whether an in-flight order stays recoverable after a crash.
"""

from decimal import Decimal
from typing import Final

from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError

# Pionex accepts letters, numbers and hyphens, up to 64 characters. A UUID4
# string is 36 characters of hex and hyphens, so it fits with room to spare --
# but this is asserted rather than assumed, because the client order id is the
# only handle that makes an in-flight order recoverable after a crash.
CLIENT_ORDER_ID_MAX_LENGTH: Final = 64
_CLIENT_ORDER_ID_ALPHABET: Final = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-"
)


def plain_decimal(value: Decimal) -> str:
    """Formats a ``Decimal`` without scientific notation.

    ``str(Decimal("0.00000001"))`` is fine, but ``str(Decimal("1E-8"))`` is
    ``'1E-8'`` -- and a ``Decimal`` that came out of a division very much can
    carry that exponent. Pionex expects a plain decimal string; ``1E-8`` is a
    rejected order at best. A futures size is ALWAYS a quotient
    (``granted * leverage / price``), so this is on the hot path there rather
    than an edge case.
    """
    return format(value.normalize(), "f")


def assert_valid_client_order_id(client_order_id: str) -> None:
    if not client_order_id or len(client_order_id) > CLIENT_ORDER_ID_MAX_LENGTH:
        raise PionexApiError(
            f"clientOrderId must be 1-{CLIENT_ORDER_ID_MAX_LENGTH} characters, "
            f"got {len(client_order_id)}"
        )
    if not set(client_order_id) <= _CLIENT_ORDER_ID_ALPHABET:
        raise PionexApiError(
            "clientOrderId must contain only letters, numbers and hyphens"
        )
