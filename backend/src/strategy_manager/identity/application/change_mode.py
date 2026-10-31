"""A user changes their own mode (multi-user design AD7; decisions 6, 7, 14, 26).

The mode decides where the next OPENING goes, and nothing else: whatever is
already open follows the mode recorded on its reservation. So each direction
refuses for its own reason.

- **To live** needs an active trade-capable key on some exchange (decision 6).
  Simulated positions may stay open: capital is counted per mode (decision 26).
- **To simulation** needs the user to hold nothing real (decision 6): the panel
  would otherwise say simulation over real money.
- **Under the brake** neither moves: everyone is forced to simulation (decision
  7), so a change could be neither seen nor trusted until the brake is off.

The row lock comes before every read that decides. An opening holds the user row
``FOR SHARE`` from before it reads the mode until its reservation commits
(``SqlAlchemyUserMode``), so under ``FOR UPDATE`` the flat check sees every real
opening that went first, and every later one sees the new mode. This use case
takes no pool advisory lock, so it cannot invert the lock order.
"""

import logging
from collections.abc import Sequence
from enum import StrEnum
from uuid import UUID

from strategy_manager.identity.application.ports import (
    CommitPort,
    LiveExposurePort,
    TradeKeysPort,
    UserRepositoryPort,
)
from strategy_manager.shared.domain.mode import Mode

logger = logging.getLogger(__name__)


class ModeRefusal(StrEnum):
    BRAKE_ON = "MODE_BRAKE_ON"
    LIVE_NEEDS_TRADE_KEY = "MODE_LIVE_NEEDS_TRADE_KEY"
    SIMULATION_NEEDS_FLAT = "MODE_SIMULATION_NEEDS_FLAT"


class ModeChangeRefusedError(Exception):
    def __init__(self, refusal: ModeRefusal, symbols: Sequence[str] = ()) -> None:
        super().__init__(refusal.value)
        self.refusal = refusal
        self.symbols = tuple(symbols)


class ChangeMode:
    def __init__(
        self,
        users: UserRepositoryPort,
        trade_keys: TradeKeysPort,
        exposure: LiveExposurePort,
        commit: CommitPort,
        *,
        brake: bool,
    ) -> None:
        self._users = users
        self._trade_keys = trade_keys
        self._exposure = exposure
        self._commit = commit
        self._brake = brake

    async def execute(self, user_id: UUID, mode: Mode) -> None:
        if self._brake:
            raise ModeChangeRefusedError(ModeRefusal.BRAKE_ON)

        await self._users.lock_for_mode_change(user_id)
        if mode is Mode.LIVE:
            if not await self._trade_keys.holds_trade_capable_key(user_id):
                raise ModeChangeRefusedError(ModeRefusal.LIVE_NEEDS_TRADE_KEY)
        else:
            symbols = await self._exposure.symbols(user_id)
            if symbols:
                raise ModeChangeRefusedError(ModeRefusal.SIMULATION_NEEDS_FLAT, symbols)

        await self._users.set_mode(user_id, mode)
        await self._commit.commit()
        logger.info("User %s set their mode to %s", user_id, mode.value)
