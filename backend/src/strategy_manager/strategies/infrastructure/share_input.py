"""``Share``: a share of the pool as the API accepts it, on every input that takes one
(owner decision 50; spec: admin-api). One definition, so the preview's ``share`` query,
the update's ``allocation_percent`` and the registration's cannot drift apart.

A share is a decimal above 0 and at most 100 with **at most 18 decimal places**, the scale
this system uses for every amount. The places are counted on the value AS WRITTEN: a
``Decimal`` keeps its exponent, so ``1.5000000000000000000`` is 19 places and ``1E+1`` is
none. Nothing is ``normalize()``d (it rounds to the context's 28 digits) and nothing is
formatted: the exponent is read, which costs the same for ``1e-999999999`` as for ``1e-2``.
Without the bound, ``1e-999999999`` (12 characters) passes the range check and writing it
in plain notation takes a text of about 1 GB, in the process that also receives the webhook.

The check runs after the range constraints, which compare numbers and allocate nothing, and
before the route or the use case sees the value. A refusal is a ``ValueError``, which the
application's 422 handler (``shared/infrastructure/validation_errors.py``) answers with a
fixed message and without the input.
"""

from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, Field

MAX_SHARE_DECIMALS = 18


def _at_most_18_decimals(value: Decimal) -> Decimal:
    exponent = value.as_tuple().exponent
    # ``exponent`` is a string only for NaN and infinity, which the range check refuses first.
    if isinstance(exponent, int) and exponent < -MAX_SHARE_DECIMALS:
        raise ValueError(f"a share has at most {MAX_SHARE_DECIMALS} decimal places")
    return value


Share = Annotated[Decimal, Field(gt=0, le=100), AfterValidator(_at_most_18_decimals)]
