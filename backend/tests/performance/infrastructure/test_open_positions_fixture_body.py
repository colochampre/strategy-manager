"""The hand-over body for the owner's fixture server is the route's own shape
(design addendum "open positions", section L, "The fixture server"; tasks.md
op.1.30).

``openspec/changes/operator-panel/visual/fixtures/open-positions.json`` is a
ready-to-paste body of ``GET /api/positions/open`` with the approved prototype's
examples. The owner's fixture configuration is an untracked file no agent reads
or edits, so the ids of the venue example are placeholders and the file says so
in its own ``_description`` field (the one key that is not part of the body).

The test loads the file, validates it against the router's response model, and
requires the round trip to be exact: what the model writes is what the file
holds, so every money is a plain string, every price has 18 places and every
instant is UTC, exactly as the route would write them.
"""

import json
from pathlib import Path
from typing import Any

from strategy_manager.performance.infrastructure.open_positions_router import (
    OpenPositionsBody,
)

FIXTURE = (
    Path(__file__).resolve().parents[4]
    / "openspec"
    / "changes"
    / "operator-panel"
    / "visual"
    / "fixtures"
    / "open-positions.json"
)


def _load() -> dict[str, Any]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _body() -> dict[str, Any]:
    data = _load()
    data.pop("_description", None)
    return data


def test_the_file_says_its_ids_are_placeholders() -> None:
    description = _load().get("_description")

    assert isinstance(description, str)
    assert "placeholder" in description.lower()
    assert "discrepancy_id" in description and "allocation_id" in description


def test_the_body_is_valid_against_the_routes_response_model_and_round_trips_exactly() -> None:
    body = _body()

    model = OpenPositionsBody.model_validate(body)

    assert json.loads(model.model_dump_json()) == body


def test_the_body_holds_every_example_the_owner_needs_to_see() -> None:
    model = OpenPositionsBody.model_validate(_body())
    positions = model.positions

    assert {p.origin for p in positions} == {"live", "rehearsal", "mixed"}
    assert any(p.figures_missing == "UNRESOLVED_SYMBOL" for p in positions)
    assert any(p.venue_disagreement is not None for p in positions)
    assert any(p.strategy_archived is True for p in positions)
    assert len({p.pool.exchange for p in positions}) >= 2, "a tab change must change the figures"
    assert len(model.orders) >= 1
    marked = [p for p in positions if p.venue_disagreement is not None]
    assert len(marked) == 1
    assert marked[0].origin == "live", "the venue example is a live position"


def test_no_example_adds_two_pools_or_serves_a_number_as_a_float() -> None:
    raw = _body()

    for position in raw["positions"]:
        for field in ("size", "opened_size", "entry_price", "fees", "margin_granted", "leverage"):
            value = position[field]
            assert value is None or isinstance(value, str), f"{field} is not a string"
        assert position["currency"] == position["pool"]["settlement_currency"]
