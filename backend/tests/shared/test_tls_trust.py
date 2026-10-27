"""The exchange clients do not trust a root Mozilla distrusted.

Every venue call goes through httpx, and httpx verifies TLS against the
``certifi`` bundle pinned in ``uv.lock``, not the system store. So patching
``ca-certificates`` on the VPS (2026-10-26) did not reach it.

On 2026-10-18 eMudhra revoked eight intermediates under
``emSign ECC Root CA - G3`` whose private keys were recoverable, and Mozilla
removed that root (bug 2083449). A certificate forged from those keys would
let anyone answer as Bybit to the worker that signs orders. A lock that pins
an older ``certifi`` again fails here.
"""

import httpx

DISTRUSTED_ROOTS = {"emSign ECC Root CA - G3"}


def _common_name(cert: dict[str, object]) -> str:
    subject = cert["subject"]
    assert isinstance(subject, tuple)
    for rdn in subject:
        for key, value in rdn:
            if key == "commonName":
                return str(value)
    return ""


def test_the_bundle_httpx_verifies_against_holds_no_distrusted_root() -> None:
    trusted = {_common_name(c) for c in httpx.create_ssl_context().get_ca_certs()}

    # The bundle was really read: an empty list would pass the check below.
    assert len(trusted) > 100
    assert trusted & DISTRUSTED_ROOTS == set()
