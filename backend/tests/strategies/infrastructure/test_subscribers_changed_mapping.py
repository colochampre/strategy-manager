"""``SubscribersChanged`` is answered 409 ``SUBSCRIBERS_CHANGED`` by archive and by
delete (multi-user tasks.md C.9), and the session is rolled back first so the locks
the refused request took are released at once."""

from typing import Any
from uuid import UUID

import pytest
from fastapi import HTTPException

from strategy_manager.strategies.application.subscriber_locks import SubscribersChanged
from strategy_manager.strategies.infrastructure import router as strategies_router

STRATEGY_ID = UUID("7256917a-9937-4a6c-b6d3-9cb2b4a9cedd")


class _Session:
    def __init__(self) -> None:
        self.rollbacks = 0

    async def rollback(self) -> None:
        self.rollbacks += 1


class _DeleteRefusing:
    async def delete(self, strategy_id: UUID) -> None:
        raise SubscribersChanged("a subscriber joined")


class _ArchiveRefusing:
    def __init__(self, **_: Any) -> None:
        pass

    async def archive(self, strategy_id: UUID) -> None:
        raise SubscribersChanged("a subscriber joined")


async def test_delete_answers_409_and_rolls_back() -> None:
    session = _Session()

    with pytest.raises(HTTPException) as refused:
        await strategies_router.delete_strategy(
            STRATEGY_ID,
            session,  # type: ignore[arg-type]
            _DeleteRefusing(),  # type: ignore[arg-type]
        )

    assert refused.value.status_code == 409
    assert refused.value.detail == {
        "error": "SUBSCRIBERS_CHANGED",
        "message": "a subscriber joined",
    }
    assert session.rollbacks == 1


async def test_archive_answers_409_and_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(strategies_router, "ArchiveStrategy", _ArchiveRefusing)
    session = _Session()

    with pytest.raises(HTTPException) as refused:
        await strategies_router.archive_strategy(
            STRATEGY_ID,
            session,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )

    assert refused.value.status_code == 409
    assert refused.value.detail == {
        "error": "SUBSCRIBERS_CHANGED",
        "message": "a subscriber joined",
    }
    assert session.rollbacks == 1
