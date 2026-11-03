"""Which jobs belong to one user, so the worker can run different users at once.

``PostgresJobQueue.claim`` reads this to keep a user's trading jobs one at a time
and in order while other users' jobs run beside them (tasks.md G.7). The kinds and
the way a job's user is read live with the modules that own those rows; this module
only names the shape, so ``shared`` imports none of them.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement

from strategy_manager.shared.application.job import JobKind

#: Given a ``JobRow`` entity or alias, the SQL expression of the user that job
#: belongs to, NULL when it cannot be read from the payload.
JobOwner = Callable[[Any], ColumnElement[Any]]


@dataclass(frozen=True)
class JobLanes:
    #: The kinds that belong to one user. Every other kind runs only on the first loop.
    kinds: frozenset[JobKind]
    owner_of: JobOwner
