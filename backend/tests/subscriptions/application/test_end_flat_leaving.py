"""``EndFlatLeaving``'s order of work, against fakes (tasks.md N2, E2.3).

A reservation released unfilled leaves a LEAVING subscription holding nothing, and
no close will ever come to end it. The sweep does. What these pin is the shape of
each decision: the user's pool lock first, one lock at a time, and a commit that
gives it back before the next user's is taken.
"""

import logging
from uuid import UUID, uuid4

import pytest

from strategy_manager.subscriptions.application.end_leaving import EndFlatLeaving
from strategy_manager.subscriptions.application.ports import LeavingSubscription

MARKET = ("bybit", "usdt-m", "USDT")
OTHER_MARKET = ("binance", "usdt-m", "USDT")


class _Listing:
    def __init__(self, *leaving: LeavingSubscription) -> None:
        self._leaving = list(leaving)

    async def leaving(self) -> list[LeavingSubscription]:
        return self._leaving


class _Lock:
    def __init__(self, log: list[object]) -> None:
        self._log = log

    async def acquire(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> None:
        self._log.append(("lock", user_id, (exchange, venue, settlement_currency)))


class _End:
    def __init__(self, log: list[object], flat: set[UUID]) -> None:
        self._log = log
        self._flat = flat

    async def end_if_flat(
        self,
        user_id: UUID,
        strategy_id: UUID,
        exchange: str,
        venue: str,
        settlement_currency: str,
    ) -> bool:
        self._log.append(("end", user_id, strategy_id, (exchange, venue, settlement_currency)))
        return user_id in self._flat


class _Commit:
    def __init__(self, log: list[object]) -> None:
        self._log = log

    async def commit(self) -> None:
        self._log.append("commit")


def _sweep(
    leaving: list[LeavingSubscription], flat: set[UUID]
) -> tuple[EndFlatLeaving, list[object]]:
    log: list[object] = []
    return (
        EndFlatLeaving(_Listing(*leaving), _Lock(log), _End(log, flat), _Commit(log)),
        log,
    )


async def test_each_decision_runs_under_its_own_pool_lock_and_gives_it_back() -> None:
    first = LeavingSubscription(uuid4(), uuid4(), MARKET)
    second = LeavingSubscription(uuid4(), uuid4(), OTHER_MARKET)
    sweep, log = _sweep([first, second], set())

    await sweep.sweep()

    assert log == [
        ("lock", first.user_id, MARKET),
        ("end", first.user_id, first.strategy_id, MARKET),
        "commit",
        ("lock", second.user_id, OTHER_MARKET),
        ("end", second.user_id, second.strategy_id, OTHER_MARKET),
        "commit",
    ]


async def test_it_counts_only_what_it_ended() -> None:
    flat = LeavingSubscription(uuid4(), uuid4(), MARKET)
    holding = LeavingSubscription(uuid4(), uuid4(), MARKET)
    sweep, _ = _sweep([flat, holding], {flat.user_id})

    assert await sweep.sweep() == 1


async def test_nothing_leaving_takes_no_lock_and_commits_nothing() -> None:
    sweep, log = _sweep([], set())

    assert await sweep.sweep() == 0
    assert log == []


async def test_only_an_ending_leaves_a_line_and_it_says_whose(
    caplog: pytest.LogCaptureFixture,
) -> None:
    flat = LeavingSubscription(uuid4(), uuid4(), MARKET)
    holding = LeavingSubscription(uuid4(), uuid4(), MARKET)
    sweep, _ = _sweep([flat, holding], {flat.user_id})

    with caplog.at_level(logging.INFO, logger="strategy_manager.subscriptions"):
        await sweep.sweep()

    [record] = [r for r in caplog.records if r.name.startswith("strategy_manager.subscriptions")]
    assert record.levelno == logging.INFO
    assert str(flat.strategy_id) in record.getMessage()
    assert str(flat.user_id) in record.getMessage()
    assert str(holding.strategy_id) not in caplog.text
