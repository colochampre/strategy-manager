"""Manual check: would the worker start on this database?

Runs the worker's own startup guard, ``assert_mode_matches_ledger``, against
``DATABASE_URL``, and writes nothing. A deploy runs it on a restored copy before
production restarts, because a refusal stops the worker: a real open allocation
whose user holds no trade-capable key on that exchange, or a record that disagrees
with its fills. Reading the same rows by hand would be a second definition of
"open", and this is the one that decides.

Prints counts, then the guard's own ERROR when it refuses: strategy names, symbols
and user ids, never a key or a URL.

Exit codes: 0 the worker would start, 1 it would refuse, 2 the check could not run.

Run from backend/: uv run python scripts/check_mode_guard.py
"""

import asyncio
import logging
import sys
from collections import Counter

from strategy_manager.accounts.infrastructure.trade_capability_adapter import (
    VaultTradeCapabilityAdapter,
)
from strategy_manager.execution.application.assert_mode_matches_ledger import (
    assert_mode_matches_ledger,
)
from strategy_manager.execution.infrastructure.mode_origin_reader import (
    SqlAlchemyModeOriginReader,
)
from strategy_manager.shared.db import engine, session_factory
from strategy_manager.shared.domain.startup_refusal import StartupRefused


async def _check() -> int:
    async with session_factory() as session:
        reader = SqlAlchemyModeOriginReader(session)
        keys = VaultTradeCapabilityAdapter(session)
        by_mode = Counter(allocation.mode.value for allocation in await reader.open_allocations())
        print(f"open allocations by recorded mode: {dict(sorted(by_mode.items()))}")
        print(f"trade-capable keys: {len(await keys.trade_capable_keys())}")
        try:
            await assert_mode_matches_ledger(reader=reader, keys=keys)
        except StartupRefused:
            print("guard: the worker would REFUSE to start; the ERROR above says why")
            return 1
    print("guard: the worker would start")
    return 0


async def _main() -> int:
    try:
        return await _check()
    except Exception as error:  # noqa: BLE001 - the type alone: a message may carry a URL.
        print(f"guard: could not run ({type(error).__name__})")
        return 2
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(message)s")
    sys.exit(asyncio.run(_main()))
