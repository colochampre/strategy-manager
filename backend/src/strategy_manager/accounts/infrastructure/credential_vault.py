"""Implements ``CredentialVaultPort`` over ``exchange_credentials``.

The vault is the only component that ever holds a decrypted API secret, and
it holds one for as long as the caller's signing call takes. Nothing here
returns, caches or logs a plaintext beyond that.

Storing a credential supersedes rather than overwrites: the previous row is
deactivated and kept. A rotated key that turns out to be wrong is then a row
to reactivate rather than a secret that no longer exists anywhere.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.domain.exchange_credential import (
    CredentialHint,
    ExchangeCredential,
)
from strategy_manager.accounts.infrastructure.models import ExchangeCredentialRow
from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.crypto import (
    Envelope,
    EnvelopeCipher,
    SealedValue,
)

API_KEY = "api_key"
API_SECRET = "api_secret"


class CredentialNotFound(InvariantViolation):
    """No active credential is stored for the requested exchange."""


class SqlAlchemyCredentialVault:
    """Envelope-encrypted credential storage."""

    def __init__(
        self, session: AsyncSession, cipher: EnvelopeCipher, clock: ClockPort
    ) -> None:
        self._session = session
        self._cipher = cipher
        self._clock = clock

    async def load(self, exchange: str) -> ExchangeCredential:
        """Decrypts the active credential for an exchange.

        Called on the worker at signing time and nowhere else.
        """
        row = await self._active_row(exchange)
        if row is None:
            raise CredentialNotFound(
                f"no active credential stored for '{exchange}'; seal one with "
                "scripts/store_pionex_credentials.py"
            )

        opened = self._cipher.unseal(_envelope_of(row), _context(row.id))
        return ExchangeCredential(
            exchange=row.exchange,
            label=row.label,
            api_key=opened[API_KEY],
            api_secret=opened[API_SECRET],
        )

    async def hints(self) -> list[CredentialHint]:
        """Every stored credential, as much of it as may be shown."""
        rows = (
            await self._session.execute(
                select(ExchangeCredentialRow)
                .where(ExchangeCredentialRow.is_active.is_(True))
                .order_by(ExchangeCredentialRow.exchange, ExchangeCredentialRow.label)
            )
        ).scalars()
        return [
            CredentialHint(
                exchange=row.exchange, label=row.label, api_key_last4=row.api_key_last4
            )
            for row in rows
        ]

    async def store(self, credential: ExchangeCredential) -> CredentialHint:
        """Seals a credential and makes it the active one for its exchange.

        The row id is generated here rather than by the database, because it
        is the encryption context: the ciphertexts must be bound to the row
        that will hold them, which means knowing the id before encrypting.
        """
        await self._deactivate_existing(credential.exchange, self._clock.now())

        row_id = uuid4()
        envelope = self._cipher.seal(
            {API_KEY: credential.api_key, API_SECRET: credential.api_secret},
            _context(row_id),
        )

        self._session.add(
            ExchangeCredentialRow(
                id=row_id,
                exchange=credential.exchange,
                label=credential.label,
                is_active=True,
                wrapped_dek=envelope.wrapped_dek,
                dek_nonce=envelope.dek_nonce,
                api_key_ciphertext=envelope.values[API_KEY].ciphertext,
                api_key_nonce=envelope.values[API_KEY].nonce,
                api_secret_ciphertext=envelope.values[API_SECRET].ciphertext,
                api_secret_nonce=envelope.values[API_SECRET].nonce,
                api_key_last4=credential.last4,
            )
        )
        await self._session.flush()
        return credential.hint()

    async def _active_row(self, exchange: str) -> ExchangeCredentialRow | None:
        result = await self._session.execute(
            select(ExchangeCredentialRow).where(
                ExchangeCredentialRow.exchange == exchange,
                ExchangeCredentialRow.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def _deactivate_existing(self, exchange: str, at: datetime) -> None:
        await self._session.execute(
            update(ExchangeCredentialRow)
            .where(
                ExchangeCredentialRow.exchange == exchange,
                ExchangeCredentialRow.is_active.is_(True),
            )
            .values(is_active=False, updated_at=at)
        )
        # The partial unique index is checked per statement, so the old row
        # must be deactivated and flushed before the new one is inserted.
        await self._session.flush()


def _envelope_of(row: ExchangeCredentialRow) -> Envelope:
    return Envelope(
        wrapped_dek=row.wrapped_dek,
        dek_nonce=row.dek_nonce,
        values={
            API_KEY: SealedValue(row.api_key_ciphertext, row.api_key_nonce),
            API_SECRET: SealedValue(row.api_secret_ciphertext, row.api_secret_nonce),
        },
    )


def _context(row_id: UUID) -> str:
    """Binds ciphertexts to their row, so a value cannot be moved between
    records without decryption failing."""
    return f"exchange_credentials/{row_id}"
