"""``ResolveUser``: the verified e-mail becomes a user (multi-user decisions 1
and 2; design AD1; tasks.md A.5).

Anyone Access lets through becomes a user on their first request, with no
approval (decision 2). ``last_seen_at`` feeds the admin's users list (decision
8), which needs minutes, not requests: writing it on every request would turn
every page load into a write, so it moves at most once a minute.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from strategy_manager.identity.application.resolve_user import ResolveUser
from strategy_manager.identity.domain.user import InvalidEmailError, User
from strategy_manager.shared.domain.mode import Mode

T0 = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)


class _Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


class _Users:
    def __init__(self) -> None:
        self.by_email: dict[str, User] = {}
        self.marked: list[tuple[UUID, datetime]] = []

    async def find_or_create(self, email: str, now: datetime) -> User:
        if email not in self.by_email:
            self.by_email[email] = User(
                id=uuid4(), email=email, created_at=now, last_seen_at=now, mode=Mode.SIMULATION
            )
        return self.by_email[email]

    async def mark_seen(self, user_id: UUID, now: datetime) -> None:
        self.marked.append((user_id, now))
        for email, user in self.by_email.items():
            if user.id == user_id:
                self.by_email[email] = replace(user, last_seen_at=now)


async def test_a_first_sign_in_creates_the_user_under_the_normal_spelling() -> None:
    users = _Users()

    user = await ResolveUser(users, _Clock()).execute("  New@Example.com ")

    assert user.email == "new@example.com"
    assert user.created_at == T0
    assert user.last_seen_at == T0
    assert list(users.by_email) == ["new@example.com"]
    assert users.marked == []


async def test_a_second_spelling_of_one_address_is_the_same_user() -> None:
    users = _Users()
    first = await ResolveUser(users, _Clock()).execute("owner@example.com")

    second = await ResolveUser(users, _Clock()).execute("OWNER@example.com")

    assert second.id == first.id
    assert len(users.by_email) == 1


async def test_a_request_within_a_minute_writes_nothing() -> None:
    users = _Users()
    clock = _Clock()
    first = await ResolveUser(users, clock).execute("owner@example.com")

    clock.current = T0 + timedelta(seconds=59)
    again = await ResolveUser(users, clock).execute("owner@example.com")

    assert again.last_seen_at == T0
    assert users.marked == []
    assert again.id == first.id


async def test_a_request_a_minute_later_moves_last_seen() -> None:
    users = _Users()
    clock = _Clock()
    first = await ResolveUser(users, clock).execute("owner@example.com")

    clock.current = T0 + timedelta(minutes=1)
    again = await ResolveUser(users, clock).execute("owner@example.com")

    assert again.last_seen_at == T0 + timedelta(minutes=1)
    assert users.marked == [(first.id, T0 + timedelta(minutes=1))]


async def test_a_claim_that_is_not_an_address_creates_no_user() -> None:
    users = _Users()

    with pytest.raises(InvalidEmailError):
        await ResolveUser(users, _Clock()).execute("not-an-address")

    assert users.by_email == {}
