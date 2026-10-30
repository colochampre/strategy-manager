"""``RegenerateWebhookSecret``: replacing a strategy's webhook secret (multi-user
design AD6; tasks.md D.3).

The author asks for a new secret when the old one leaked or the alert is being
rebuilt. The hash and the last four are replaced together and the plain secret is
returned once; the old
secret stops authenticating at the webhook from the commit on.

**Another user's strategy is a strategy that does not exist** (AD8): the caller hands
in the author's own repository, which cannot see it, so the answer is the same
``UnknownStrategy`` and cannot tell the two apart.

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
    webhook_secret_last4,
)


class RegenerateWebhookSecret:
    def __init__(self, repository: StrategyRepositoryPort, commit: CommitPort) -> None:
        self._repository = repository
        self._commit = commit

    async def regenerate(self, strategy_id: UUID) -> str:
        """The new plain secret. Nothing is logged: neither it nor its hash.

        The repository is the author's own (``AuthorStrategyRepository``): a strategy
        it cannot see is another user's or none, and both are ``UnknownStrategy``."""
        strategy = await self._repository.get_by_id_for_update(strategy_id)
        if strategy is None:
            raise UnknownStrategy(f"no strategy registered under id {strategy_id}")
        if strategy.archived_at is not None:
            raise StrategyArchived(
                f"strategy {strategy_id} ({strategy.name!r}) is archived "
                "and read-only; nothing about it may be edited"
            )

        secret = new_webhook_secret()
        await self._repository.replace_webhook_secret(
            strategy_id, hash_webhook_secret(secret), webhook_secret_last4(secret)
        )
        await self._commit.commit()
        return secret
