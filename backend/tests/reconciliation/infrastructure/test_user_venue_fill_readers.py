"""``UserVenueFillReaders``: a user's own registry, never another user's."""

from uuid import UUID

from strategy_manager.reconciliation.application.ports import VenueFillReaderPort
from strategy_manager.reconciliation.infrastructure.user_venue_fill_readers import (
    UserVenueFillReaders,
)

ALICE = UUID("a11ce000-0000-4000-8000-000000000001")
BOB = UUID("b0b00000-0000-4000-8000-000000000002")
STRANGER = UUID("5712a000-0000-4000-8000-000000000003")


class _Registry:
    def for_pool(self, exchange: str, venue: str) -> VenueFillReaderPort:
        raise NotImplementedError


def test_each_user_resolves_to_their_own_registry() -> None:
    alice, bob, unkeyed = _Registry(), _Registry(), _Registry()
    readers = UserVenueFillReaders({ALICE: alice, BOB: bob}, unkeyed)

    assert readers.for_user(ALICE) is alice
    assert readers.for_user(BOB) is bob


def test_an_unknown_user_resolves_to_the_unkeyed_registry_not_to_anyone_elses() -> None:
    alice, unkeyed = _Registry(), _Registry()
    readers = UserVenueFillReaders({ALICE: alice}, unkeyed)

    assert readers.for_user(STRANGER) is unkeyed
