"""Bybit V5 REST adapter.

The second venue. It exists because Pionex does not offer futures order
placement over its API to public users, which is a product decision and not
something a client can work around.

Structured as the sibling of ``pionex/``: signer, transport, read client,
trade client, factory. That symmetry is not decoration -- it is the proof that
``ExchangePort`` was the right seam. Everything above the adapter layer is
unchanged by adding this.
"""

EXCHANGE = "bybit"
