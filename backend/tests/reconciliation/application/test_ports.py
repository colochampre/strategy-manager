"""``VenueFill`` vs ``execution.domain.fill.Fill`` (design decision 9,
Blocker c). An order-scoped fetch inherits its side from the order it
settled; a window fetch has no order, so ``VenueFill`` carries ``side`` and
``Fill`` does not. Corrects explore #230 Q3's claim that the existing types
already cover every field a window fetch needs.
"""

from dataclasses import fields

from strategy_manager.execution.domain.fill import Fill
from strategy_manager.reconciliation.application.ports import VenueFill


def test_venue_fill_carries_side_field_fill_does_not() -> None:
    venue_fill_field_names = {field.name for field in fields(VenueFill)}
    fill_field_names = {field.name for field in fields(Fill)}

    assert "side" in venue_fill_field_names
    assert "side" not in fill_field_names
