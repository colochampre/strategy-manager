"""The injected pieces of the store scripts, as recording fakes.

``store_binance_credentials.main`` and ``store_bybit_credentials.main`` take the
terminal prompt and the saver as arguments, so a test drives the whole script
without a terminal, a database, a master key or a venue (rule 1). What matters
is what these record: whether the prompt was ever called, whether a saver was
ever built, and which confirmations reached ``SaveCredential``.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

from strategy_manager.accounts.application.save_credential import SaveCredential, SaveResult
from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential
from strategy_manager.accounts.domain.key_policy import OwnerConfirmations
from tests.accounts.fakes import (
    FixedRealExposure,
    RecordingCommit,
    RecordingInspector,
    RecordingPoolLock,
    RecordingPoolWriter,
    RecordingWriter,
    TickingClock,
    as_pools,
    as_writer,
    registry_for,
)
from tests.owner import OWNER_ID

OWNER_EMAIL = "owner-of-the-key@example.com"
"""The ``--user-email`` a test passes; ``ScriptSession`` resolves it to
``OWNER_ID``, as the real saver resolves an e-mail to its ``users`` row."""


class ScriptSession:
    """One run of a store script against fakes.

    By default the saver is a REAL ``SaveCredential`` over a recording
    inspector and writer, so the script's outcome comes from the actual policy.
    Pass ``result`` to force one, or ``save_error`` to make the saver raise.

    ``make_saver`` receives the ``--user-email`` and records it in ``emails``.
    An e-mail other than ``OWNER_EMAIL`` builds no saver, as the real one
    refuses an e-mail no user is registered with; the key is saved for
    ``OWNER_ID`` otherwise, and ``users`` records whose it was.
    """

    def __init__(
        self,
        credential: ExchangeCredential | None,
        *,
        inspector: RecordingInspector | None = None,
        result: SaveResult | None = None,
        save_error: Exception | None = None,
        master_key_ok: bool = True,
    ) -> None:
        self.credential = credential
        self.inspector = inspector or RecordingInspector()
        self.writer = RecordingWriter()
        self.pools = RecordingPoolWriter()
        self.prompt_calls = 0
        self.saver_requests = 0
        self.emails: list[str] = []
        self.users: list[UUID] = []
        self.saves: list[tuple[ExchangeCredential, OwnerConfirmations]] = []
        self._result = result
        self._save_error = save_error
        self._master_key_ok = master_key_ok
        self._use_case = SaveCredential(
            registry_for(self.inspector),
            as_writer(self.writer),
            as_pools(self.pools),
            RecordingCommit(),
            TickingClock(),
            RecordingPoolLock(),
            FixedRealExposure(),
        )

    def prompt(self) -> ExchangeCredential | None:
        self.prompt_calls += 1
        return self.credential

    async def make_saver(
        self, user_email: str
    ) -> Callable[[ExchangeCredential, OwnerConfirmations], Awaitable[SaveResult]] | None:
        self.saver_requests += 1
        self.emails.append(user_email)
        if not self._master_key_ok or user_email != OWNER_EMAIL:
            return None
        return self._save

    async def _save(
        self, credential: ExchangeCredential, confirmations: OwnerConfirmations
    ) -> SaveResult:
        self.saves.append((credential, confirmations))
        if self._save_error is not None:
            raise self._save_error
        if self._result is not None:
            return self._result
        self.users.append(OWNER_ID)
        return await self._use_case.execute(OWNER_ID, credential, confirmations)
