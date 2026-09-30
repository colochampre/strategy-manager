"""The rows behind ``GET /api/credentials``: one overview per exchange.

**The listing rule (decisions 20 and 21).** An exchange is listed when it has an
active credential, OR any credential history (a superseded or deactivated
row), OR an enabled pool. The last is the DEGRADED case: an exchange the system
is meant to trade with that has no key, which the panel must be able to show.
An exchange with none of the three does not exist as far as this list goes.

**It reads the snapshot and nothing else.** No venue is asked, and nothing is
decrypted: the query names the columns the panel shows, and there is no cipher
here to decrypt with. A key is visible only as its last four characters and the
facts recorded when it was saved (rule 8).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.domain.credential_overview import CredentialOverview, StoredKey
from strategy_manager.accounts.infrastructure.credential_vault import facts_of
from strategy_manager.accounts.infrastructure.models import CapitalPoolRow, ExchangeCredentialRow

_ROW = ExchangeCredentialRow


class SqlAlchemyCredentialListing:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_overview(self) -> list[CredentialOverview]:
        rows = (
            await self._session.execute(
                select(
                    _ROW.exchange,
                    _ROW.is_active,
                    _ROW.label,
                    _ROW.api_key_last4,
                    _ROW.created_at,
                    _ROW.trade_capable,
                    _ROW.trade_capability_source,
                    _ROW.trade_confirmed_at,
                    _ROW.withdraw_check,
                    _ROW.withdraw_confirmed_at,
                    _ROW.validated_at,
                    _ROW.internal_transfer,
                )
            )
        ).all()
        with_enabled_pool = set(
            (
                await self._session.execute(
                    select(CapitalPoolRow.exchange).where(CapitalPoolRow.enabled.is_(True))
                )
            ).scalars()
        )

        active = {
            row.exchange: StoredKey(
                label=row.label,
                last4=row.api_key_last4,
                stored_at=row.created_at,
                facts=facts_of(row),
            )
            for row in rows
            if row.is_active
        }
        exchanges = {row.exchange for row in rows} | with_enabled_pool
        return [
            CredentialOverview(exchange, active.get(exchange)) for exchange in sorted(exchanges)
        ]
