from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from strategy_manager.main import create_app
from strategy_manager.shared.config import get_settings


@pytest.fixture(autouse=True)
def _tests_never_send_operator_alerts(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_settings()`` reads the developer's ``.env``, which may have
    operator alerts configured. The real ``main.lifespan`` would then install
    the Telegram bridge on the root logger, and every ERROR a test logs on
    purpose would reach the real chat. Alerts are switched off on that shared
    object for every test; tests of the alerter build their own ``Settings``.
    """
    monkeypatch.setattr(get_settings(), "alerts_enabled", False)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
