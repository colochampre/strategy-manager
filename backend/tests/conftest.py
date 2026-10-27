from collections.abc import AsyncIterator, Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url

from strategy_manager.main import create_app
from strategy_manager.shared.config import get_settings
from tests.report_scrub import scrub_credentials


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Iterator[None]:
    """A failed report reaches the terminal with no database URL that carries
    credentials and no database password (``tests/report_scrub.py``). Captured
    output and logs are cleaned too: a test may log what it asserts on."""
    outcome = yield
    report = outcome.get_result()  # type: ignore[attr-defined]
    if not report.failed:
        return
    secrets = [make_url(get_settings().database_url).password or ""]
    text = str(report.longrepr)
    clean = scrub_credentials(text, secrets)
    if clean != text:
        report.longrepr = clean
    report.sections = [
        (title, scrub_credentials(content, secrets)) for title, content in report.sections
    ]


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
