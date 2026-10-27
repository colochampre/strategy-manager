"""Which fill readers read ONE user's account (multi-user design AD10).

Implements ``UserVenueFillReadersPort`` over a fixed set of per-user
registries. A user absent from the set -- one with no active key this cycle, or
no enabled pool any more while a CONFIRMED discrepancy of theirs is still on
record -- resolves to ``unkeyed``, a registry the caller builds out of readers
that fail with the tolerated ``VenueFillReadError``. There is deliberately no
fallback to ANOTHER user's registry: that would read someone else's account and
book its fills against this user.
"""

from collections.abc import Mapping
from uuid import UUID

from strategy_manager.reconciliation.application.ports import VenueFillReaderRegistryPort


class UserVenueFillReaders:
    def __init__(
        self,
        by_user: Mapping[UUID, VenueFillReaderRegistryPort],
        unkeyed: VenueFillReaderRegistryPort,
    ) -> None:
        self._by_user = dict(by_user)
        self._unkeyed = unkeyed

    def for_user(self, user_id: UUID) -> VenueFillReaderRegistryPort:
        return self._by_user.get(user_id, self._unkeyed)
