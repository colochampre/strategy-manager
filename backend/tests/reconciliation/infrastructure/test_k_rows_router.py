"""``GET /reconciliation/confirmed`` and design § K (owner decision 66,
2026-10-16), on real PostgreSQL behind the real router:

* row 3 (cd.3.3): the badge does not depend on the booking chain, because the
  route computes the group from the rows. The watchdog's own ERROR for a dead
  ``RECONCILIATION_PREPARE_BOOKING`` chain is pre-existing and is pinned by
  ``tests/shared/infrastructure/test_booking_prepare_wiring.py::
  test_the_watchdog_reads_the_same_tuple_the_seeder_does`` (and the
  registration test beside it), which this file does not rewrite;
* row 12 (cd.3.12): a booking written and then the venue moves again.
"""

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyKind
from tests.reconciliation.infrastructure.test_confirmed_router import (
    HEADERS,
    _approved_proposal,
    _discrepancy,
    _settings,  # noqa: F401  (autouse: admin token, DRY_RUN off, the 300 s grace)
    _strategy_and_allocation,
    client,  # noqa: F401  (the app with the real router over the test database)
)

pytestmark = pytest.mark.integration


async def test_a_discrepancy_confirmed_six_minutes_ago_with_no_proposal_at_all_needs_the_owner(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # The booking chain never ran: there is no proposal row of any state.
    discrepancy_id = await _discrepancy(
        pg_session_factory, symbol="HHHUSDT", confirmed_ago=timedelta(minutes=6)
    )
    async with pg_session_factory() as session:
        proposals = (
            await session.execute(text("SELECT count(*) FROM booking_proposals"))
        ).scalar_one()
    assert proposals == 0

    body: dict[str, Any] = (await client.get("/reconciliation/confirmed", headers=HEADERS)).json()

    assert body["needs_owner_count"] == 1
    [item] = body["needs_owner"]
    assert item["discrepancy_id"] == str(discrepancy_id)
    assert item["reason"] == "NOT_BOOKED"
    assert body["being_booked"] == []
    assert body["booked"] == []


async def test_the_same_discrepancy_confirmed_four_minutes_ago_is_still_being_booked(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The other side of the 300 s grace, so the six-minute case above is not
    NEEDS_OWNER for any reason but its age."""

    discrepancy_id = await _discrepancy(
        pg_session_factory, symbol="IIIUSDT", confirmed_ago=timedelta(minutes=4)
    )

    body: dict[str, Any] = (await client.get("/reconciliation/confirmed", headers=HEADERS)).json()

    assert body["needs_owner_count"] == 0
    assert [item["discrepancy_id"] for item in body["being_booked"]] == [str(discrepancy_id)]
    assert body["being_booked"][0]["reason"] is None


@pytest.mark.parametrize(
    ("confirmed_ago", "group"),
    [(timedelta(seconds=10), "being_booked"), (timedelta(hours=1), "needs_owner")],
)
async def test_after_a_booking_the_venue_moving_again_puts_the_item_back_and_keeps_the_booking(
    client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],
    confirmed_ago: timedelta,
    group: str,
) -> None:
    strategy_id, allocation_id = await _strategy_and_allocation(pg_session_factory)
    # The row now shows the venue at 0.2, a difference the booking never saw:
    # the proposal froze venue 0 / ledger 0.5 when it was booked.
    discrepancy_id = await _discrepancy(
        pg_session_factory,
        symbol="JJJUSDT",
        kind=DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION,
        allocations=[allocation_id],
        confirmed_ago=confirmed_ago,
        venue_net_base=Decimal("0.2"),
        ledger_net_base=Decimal("0.5"),
    )
    proposal_id = await _approved_proposal(
        pg_session_factory,
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        symbol="JJJUSDT",
        observed=(Decimal("0"), Decimal("0.5")),
    )

    body: dict[str, Any] = (await client.get("/reconciliation/confirmed", headers=HEADERS)).json()

    other = "needs_owner" if group == "being_booked" else "being_booked"
    assert [item["discrepancy_id"] for item in body[group]] == [str(discrepancy_id)]
    assert body[other] == []
    assert body["needs_owner_count"] == len(body["needs_owner"])
    if group == "needs_owner":
        assert body["needs_owner"][0]["reason"] == "NOT_BOOKED"
    # The old booking stays where it was, and says its discrepancy is open.
    [booking] = body["booked"]
    assert booking["proposal_id"] == str(proposal_id)
    assert booking["discrepancy_id"] == str(discrepancy_id)
    assert booking["discrepancy_open"] is True


async def test_a_booking_the_venue_has_not_moved_away_from_is_only_in_booked(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The control of the case above: the same booking with the venue where
    the proposal froze it is in no list but ``booked``."""

    strategy_id, allocation_id = await _strategy_and_allocation(pg_session_factory)
    discrepancy_id = await _discrepancy(
        pg_session_factory,
        symbol="KKKUSDT",
        allocations=[allocation_id],
        confirmed_ago=timedelta(hours=1),
        venue_net_base=Decimal("0"),
        ledger_net_base=Decimal("0.5"),
    )
    await _approved_proposal(
        pg_session_factory,
        discrepancy_id=discrepancy_id,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        symbol="KKKUSDT",
        observed=(Decimal("0"), Decimal("0.5")),
    )

    body: dict[str, Any] = (await client.get("/reconciliation/confirmed", headers=HEADERS)).json()

    assert body["needs_owner"] == []
    assert body["being_booked"] == []
    assert [b["discrepancy_id"] for b in body["booked"]] == [str(discrepancy_id)]
