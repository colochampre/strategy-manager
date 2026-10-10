"""The webhook's public origin (design.md, unit 12f addendum, sections F and O;
spec: admin-api "The Webhook's Origin Is Served By Its Own Route").

``WEBHOOK_PUBLIC_ORIGIN`` is the host TradingView posts to, which is not the
panel's (decision 5). ``parse_webhook_origin`` reads it: an origin and nothing
more. The panel adds the path, so a path, a query or a fragment is refused.

| Input | Result |
| --- | --- |
| empty | unset: ``None``, not an error |
| ``http`` or ``https``, a host, an optional port | the normalised origin |
| anything else | ``InvalidWebhookOrigin`` |

Normalised means the scheme and host in lower case, one trailing slash dropped
and the scheme's default port dropped. Refused: no scheme or a scheme other than
``http`` and ``https``; an empty host; anything after the authority; a user or a
password (it would put a credential on screen and in the clipboard); a space, a
control character, a backslash, a character outside ASCII; a port that is not a
number in range, and a port that is present and empty; a bracketed IPv6 literal
(TradingView does not post to IPv6); a host that ends in a dot.

**A refusal never carries the value.** The value may be refused exactly because
it holds a credential, so every reason is a fixed sentence that quotes none of
the input.

Pure standard library (``urllib.parse``), no framework, no I/O.
"""

from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}
_HOST_PUNCTUATION = frozenset("-.")
_MAX_PORT = 65535


class InvalidWebhookOrigin(Exception):
    """The configured origin is malformed. The message is a fixed reason and
    never quotes the value."""


def _refuse(reason: str) -> InvalidWebhookOrigin:
    return InvalidWebhookOrigin(reason)


def parse_webhook_origin(raw: str) -> str | None:
    """The normalised origin, ``None`` when ``raw`` is empty (unset), or
    ``InvalidWebhookOrigin`` when it is malformed."""
    if raw == "":
        return None
    if not raw.isascii():
        raise _refuse("the origin contains a character outside ASCII")
    if any(ord(char) <= 0x20 or ord(char) == 0x7F for char in raw):
        raise _refuse("the origin contains a space or a control character")
    if "\\" in raw:
        raise _refuse("the origin contains a backslash")
    if "?" in raw or "#" in raw:
        raise _refuse("the origin has a query or a fragment")
    try:
        parts = urlsplit(raw)
    except ValueError:
        raise _refuse("the origin cannot be read as a URL") from None

    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        raise _refuse("the scheme must be http or https")
    if parts.path not in ("", "/"):
        raise _refuse("the origin has a path")

    authority = parts.netloc
    if "@" in authority:
        raise _refuse("the origin carries a credential")
    if "[" in authority or "]" in authority:
        raise _refuse("an IPv6 literal is not accepted")

    host, separator, port_text = authority.partition(":")
    if host == "":
        raise _refuse("the host is empty")
    if host.endswith("."):
        raise _refuse("the host ends in a dot")
    if not all(char.isalnum() or char in _HOST_PUNCTUATION for char in host):
        raise _refuse("the host contains a character that is not allowed")

    origin = f"{scheme}://{host.lower()}"
    if not separator:
        return origin
    if not port_text.isdigit():
        raise _refuse("the port must be a number")
    port = int(port_text)
    if not 1 <= port <= _MAX_PORT:
        raise _refuse("the port is out of range")
    if port == _DEFAULT_PORTS[scheme]:
        return origin
    return f"{origin}:{port}"
