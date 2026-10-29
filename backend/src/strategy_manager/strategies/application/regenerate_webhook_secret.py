"""``RegenerateWebhookSecret``: replacing a strategy's webhook secret (multi-user
design AD6; tasks.md D.3).

The author asks for a new secret when the old one leaked or the alert is being
rebuilt. The hash is replaced and the plain secret is returned once; the old
secret stops authenticating at the webhook from the commit on.

**Another user's strategy is a strategy that does not exist** (AD8): the same
``UnknownStrategy``, so the answer cannot tell the two apart.

**An archived strategy is refused**, as every other write on one is
(``StrategyArchived``). The row is read ``FOR UPDATE``, the lock ``UpdateStrategy``
takes, so a concurrent archive and a regenerate serialize on it. This path takes no
pool advisory lock, because it touches no capital.
"""

from uuid import UUID

from strategy_manager.strategies.application.ports import CommitPort, StrategyRepositoryPort
from strategy_manager.strategies.application.update_strategy import (
    StrategyArchived,
    UnknownStrategy,
)
from strategy_manager.strategies.domain.webhook_secret import (
    hash_webhook_secret,
    new_webhook_secret,
)


class RegenerateWebhookSecret:
    def __init__(self, repository: StrategyRepositoryPort, commit: CommitPort) -> None:
        self._repository = repository
        self._commit = commit

    async def regenerate(self, strategy_id: UUID, author_id: UUID) -> str:
        """The new plain secret. Nothing is logged: neither it nor its hash."""
        strategy = await self._repository.get_by_id_for_update(strategy_id)
        if strategy is None or strategy.author_id != author_id:
            raise UnknownStrategy(f"no strategy registered under id {strategy_id}")
        if strategy.archived_at is not None:
            raise StrategyArchived(
                f"strategy {strategy_id} ({strategy.name!r}) is archived "
                "and read-only; nothing about it may be edited"
            )

        secret = new_webhook_secret()
        await self._repository.replace_webhook_secret_hash(strategy_id, hash_webhook_secret(secret))
        await self._commit.commit()
        return secret
