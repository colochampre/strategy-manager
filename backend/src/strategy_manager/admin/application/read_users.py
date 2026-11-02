"""``ReadUsers``: every user with their state (tasks.md F.7, decision 8)."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from strategy_manager.admin.application.ports import UserExchange, UsersSourcePort
from strategy_manager.shared.domain.mode import Mode


@dataclass(frozen=True, slots=True)
class UserState:
    email: str
    display_name: str | None
    mode: Mode
    exchanges_with_key: tuple[str, ...]
    exchanges_with_no_key: tuple[str, ...]
    subscriptions: int
    open_positions: int
    last_seen_at: datetime


def _by_user(pairs: frozenset[UserExchange]) -> dict[UUID, list[str]]:
    exchanges: dict[UUID, list[str]] = {}
    for user_id, exchange in sorted(pairs, key=lambda pair: pair[1]):
        exchanges.setdefault(user_id, []).append(exchange)
    return exchanges


class ReadUsers:
    def __init__(self, source: UsersSourcePort) -> None:
        self._source = source

    async def read(self) -> tuple[UserState, ...]:
        users = await self._source.users()
        coverage = await self._source.coverage()
        subscriptions = await self._source.live_subscriptions()
        positions = Counter(await self._source.open_allocation_owners())

        with_key = _by_user(coverage.active_keys)
        with_no_key = _by_user(coverage.enabled_pools - coverage.active_keys)
        return tuple(
            UserState(
                email=user.email,
                display_name=user.display_name,
                mode=user.mode,
                exchanges_with_key=tuple(with_key.get(user.id, ())),
                exchanges_with_no_key=tuple(with_no_key.get(user.id, ())),
                subscriptions=subscriptions.get(user.id, 0),
                open_positions=positions[user.id],
                last_seen_at=user.last_seen_at,
            )
            for user in users
        )
