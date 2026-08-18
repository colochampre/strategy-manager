"""``Fill``: what ``ExchangePort.submit`` returns on a successful order
(design.md § execution/ and ledger/ (slice 5); spec: trade-execution § Fill
Recording).
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Fill:
    """Exchange-reported fill details. ``price`` here is the real fill
    price — never the alert's bar-close reference price used to size the
    order."""

    exchange_order_id: str
    exchange_fill_id: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    fee_currency: str
    filled_at: datetime
