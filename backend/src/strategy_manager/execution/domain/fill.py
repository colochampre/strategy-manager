"""``Fill``: what ``ExchangePort.submit`` returns on a successful order
(design.md § execution/ and ledger/ (slice 5); spec: trade-execution § Fill
Recording).
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

# Every fill the DRY_RUN fake exchange mints carries this prefix on its
# ``exchange_fill_id``. It is the single definition: the fake mints with it and
# performance reads exclude on it, so a rehearsal fill can never reach a
# figure (design.md § 12). Safe as a marker because Bybit ``execId`` values are
# UUIDs and Binance trade ids are integers -- no live fill can start with it.
# The value is a data contract, too: ledger rows already written carry it.
REHEARSAL_FILL_ID_PREFIX = "fake-fill-"


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
