"""Startup invariant 5: ``MASTER_ENCRYPTION_KEY`` must build a cipher.

The API never decrypts a credential, but it does SEAL them: ``PUT
/api/credentials/{exchange}`` needs the cipher. Without this check a missing or
malformed key is found by the first save, as a 503, long after the deploy that
broke it. The worker already refuses the same key at boot (``worker._run_worker``);
this is the API's half of that rule, using the same constructor so the two
processes cannot disagree about what a usable key is.

Decision 29 applies: uvicorn reports a failed lifespan on the ``uvicorn`` logger,
which has ``propagate=False``, so its ERROR never reaches the root logger the alert
bridge is installed on. The refusal therefore logs its own ERROR through this
module's logger (which does propagate) BEFORE raising.

**The key is never logged.** ``EnvelopeCipher.from_base64`` raises fixed messages
(or the decoded length), and this module logs that message and nothing else: no
``exc_info``, no settings value, no argument that could carry the key.
"""

import logging

from strategy_manager.shared.config import Settings
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.crypto import EnvelopeCipher

logger = logging.getLogger(__name__)


def assert_master_key_usable(settings: Settings) -> None:
    try:
        EnvelopeCipher.from_base64(settings.master_encryption_key)
    except InvariantViolation as refused:
        logger.error("refusing to start: %s", refused)
        raise
