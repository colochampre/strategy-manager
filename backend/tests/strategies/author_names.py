"""``AuthorNamesPort`` for tests that do not exercise the name rule (decision 27)."""

from uuid import UUID


class FixedAuthorNames:
    """Every author has a name, unless a test says otherwise."""

    def __init__(self, *, named: bool = True) -> None:
        self.named = named
        self.asked: list[UUID] = []

    async def has_display_name(self, user_id: UUID) -> bool:
        self.asked.append(user_id)
        return self.named
