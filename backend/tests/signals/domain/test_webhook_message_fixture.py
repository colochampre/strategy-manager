"""Cross-language guard: the panel's webhook message must stay parseable.

The operator panel renders the alert message the owner pastes into TradingView
from ``frontend/src/features/strategies/webhook-message.fixture.json``. The
frontend test reads the same file, so this module is the other half of one
contract: TradingView fills every ``{{...}}`` placeholder at alert time, the
panel fills ``signal_type`` with the strategy id, and what results must go
through ``TradingViewAlert.from_payload``. A fixture edited into a shape the
parser refuses would only be found by a real alert failing, which is a
position the strategy never opened.

This test only READS the fixture. It never writes it.
"""

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from strategy_manager.signals.domain.alert import (
    TradingViewAlert,
    derive_idempotency_key,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_FIXTURE = _REPO_ROOT / "frontend" / "src" / "features" / "strategies" / "webhook-message.fixture.json"

_PLACEHOLDER = re.compile(r"\{\{([^{}]+)\}\}")

# What TradingView substitutes at alert time, in the form it substitutes it.
# The ticker is TradingView's own spelling (a perpetual carries ``.P``), never
# the venue's bare symbol or Pionex's ``_PERP`` one.
_TRADINGVIEW_SAMPLES = {
    "strategy.order.action": "buy",
    "strategy.order.contracts": "0.5",
    "strategy.position_size": "1.25",
    "close": "2467.5",
    "ticker": "STXUSDT.P",
    "timenow": "2026-10-03T10:15:30Z",
}

_STRATEGY_ID = "5d0a0f4e-3b0c-4b43-9d52-0f6a1c1f2a77"


def _read_fixture_text() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


def _payload_after_substitution() -> dict[str, Any]:
    text = _PLACEHOLDER.sub(lambda match: _TRADINGVIEW_SAMPLES[match.group(1)], _read_fixture_text())
    payload: dict[str, Any] = json.loads(text)
    # The panel puts the strategy id where the fixture holds its own token.
    payload["signal_type"] = _STRATEGY_ID
    return payload


def test_frontend_fixture_parses_through_tradingview_alert_from_payload_after_placeholder_substitution() -> None:
    placeholders = set(_PLACEHOLDER.findall(_read_fixture_text()))
    assert placeholders == set(_TRADINGVIEW_SAMPLES), (
        "the fixture's {{...}} placeholders and this test's samples must be the same set, "
        "so a new placeholder cannot slip in unparsed"
    )

    alert = TradingViewAlert.from_payload(_payload_after_substitution())

    assert alert.action == "buy"
    assert alert.contracts == Decimal("0.5")
    assert alert.position_size == Decimal("1.25")
    assert alert.price == Decimal("2467.5")
    assert alert.symbol == "STXUSDT.P"
    assert alert.time == "2026-10-03T10:15:30Z"
    assert UUID(alert.signal_type) == UUID(_STRATEGY_ID)
    assert len(derive_idempotency_key(alert)) == 64
