"""A failed test's report carries no database URL with credentials and no
password: the root ``conftest`` passes every failure through
``scrub_credentials``. Most test modules build their own throwaway URLs, so
masking one helper's URL was not enough (seen 2026-10-27).

The secrets here are made up, and each check is held in a bool so that a
failure of this module prints none of them either."""

import pytest

from tests.report_scrub import scrub_credentials

pytest_plugins = ["pytester"]

_URL = "postgresql+asyncpg://tester:s3cret-pw@localhost:5432/strategy_manager_test_x"


def test_a_url_with_credentials_is_replaced_whole() -> None:
    text = f"E   assert 1 == _scalar('{_URL}', 'SELECT 1')"

    clean = scrub_credentials(text, [])

    gone = "s3cret-pw" not in clean and "tester" not in clean
    assert gone
    assert "<database url>" in clean


def test_a_bare_password_is_replaced() -> None:
    clean = scrub_credentials("password='s3cret-pw' leaked", ["s3cret-pw"])

    gone = "s3cret-pw" not in clean
    assert gone
    assert "<redacted>" in clean


def test_a_url_without_credentials_and_other_text_are_left_alone() -> None:
    text = "GET https://api.bybit.com/v5/market/time answered 200"

    assert scrub_credentials(text, ["", "s3cret-pw"]) == text


def test_the_root_conftest_scrubs_a_real_failure_report(pytester: pytest.Pytester) -> None:
    """The hook itself, end to end: a failing assertion whose call carries a URL
    with credentials, and a print of it, as pytest would show them."""
    pytester.makeconftest("from tests.conftest import pytest_runtest_makereport  # noqa: F401")
    pytester.makepyfile(
        f"""
        def _echo(url, value):
            print("connecting to " + url)
            return value

        def test_leaks():
            assert _echo("{_URL}", 1) == 2
        """
    )

    result = pytester.runpytest_inprocess("-p", "no:cacheprovider", "--tb=long")
    output = "\\n".join(result.outlines)

    failed = result.ret != 0
    gone = "s3cret-pw" not in output and "tester:" not in output
    assert failed
    assert gone
    assert "<database url>" in output
