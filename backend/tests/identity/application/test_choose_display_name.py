"""``ChooseDisplayName`` (multi-user decision 27; tasks.md F.1)."""

from uuid import UUID, uuid4

import pytest

from strategy_manager.identity.application.choose_display_name import ChooseDisplayName
from strategy_manager.identity.application.ports import DisplayNameTakenError
from strategy_manager.identity.domain.display_name import InvalidDisplayNameError

USER_ID = uuid4()


class Users:
    def __init__(self, *, taken: bool = False) -> None:
        self.taken = taken
        self.stored: list[tuple[UUID, str]] = []

    async def set_display_name(self, user_id: UUID, name: str) -> None:
        if self.taken:
            raise DisplayNameTakenError
        self.stored.append((user_id, name))


class Commit:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


async def test_the_normal_spelling_is_stored_and_returned() -> None:
    users, commit = Users(), Commit()

    name = await ChooseDisplayName(users, commit).execute(USER_ID, "  Ana  ")  # type: ignore[arg-type]

    assert name == "Ana"
    assert users.stored == [(USER_ID, "Ana")]
    assert commit.commits == 1


async def test_an_invalid_name_stores_nothing() -> None:
    users, commit = Users(), Commit()

    with pytest.raises(InvalidDisplayNameError):
        await ChooseDisplayName(users, commit).execute(USER_ID, "a@b")  # type: ignore[arg-type]

    assert users.stored == []
    assert commit.commits == 0


async def test_a_name_someone_holds_commits_nothing() -> None:
    users, commit = Users(taken=True), Commit()

    with pytest.raises(DisplayNameTakenError):
        await ChooseDisplayName(users, commit).execute(USER_ID, "Ana")  # type: ignore[arg-type]

    assert commit.commits == 0
