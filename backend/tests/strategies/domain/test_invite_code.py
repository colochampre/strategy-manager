"""An invitation code (multi-user decision 41; tasks.md K.2).

Eight Crockford base32 characters, shown as ``XXXX-XXXX``. Typed back, case, dashes
and spaces are ignored, and Crockford's look-alikes read as the digit they resemble
(``I`` and ``L`` as ``1``, ``O`` as ``0``). The code is stored only as its SHA-256
hex, beside a hint of its last four characters, and lives 7 days from its making. A
code is live until it expires, is revoked or is redeemed.
"""

import hashlib
import re
from datetime import UTC, datetime, timedelta

import pytest

from strategy_manager.strategies.domain.invite_code import (
    ATTEMPT_WINDOW,
    CODE_LIFETIME,
    MAX_FAILED_ATTEMPTS,
    DeadCode,
    InviteCode,
    IssuedCode,
    may_attempt,
)

# What ``ck_invite_codes_code_hash_shape`` and ``ck_invite_codes_hint_shape`` check.
DB_HASH_SHAPE = re.compile(r"^[0-9a-f]{64}$")
DB_HINT_SHAPE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{4}$")
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
T0 = datetime(2026, 11, 7, 12, tzinfo=UTC)


class _Counting:
    """A ``randbelow`` that answers ``start``, ``start + 1``, ... so a generated code
    is known, and records the bounds it was asked for."""

    def __init__(self, start: int) -> None:
        self.next = start
        self.bounds: list[int] = []

    def __call__(self, bound: int) -> int:
        self.bounds.append(bound)
        value = self.next % bound
        self.next += 1
        return value


def test_a_generated_code_draws_eight_characters_of_crockford_base32() -> None:
    randbelow = _Counting(10)

    code = InviteCode.generate(randbelow)

    assert randbelow.bounds == [32] * 8
    assert code.display == "ABCD-EFGH"


def test_a_generated_code_is_random_by_default() -> None:
    first, second = InviteCode.generate(), InviteCode.generate()

    assert first.display != second.display
    assert re.fullmatch(rf"[{CROCKFORD}]{{4}}-[{CROCKFORD}]{{4}}", first.display)


@pytest.mark.parametrize(
    "typed",
    ["K7QM-4XPD", "k7qm-4xpd", "K7QM4XPD", " k7qm 4xpd ", "K7-QM-4X-PD"],
    ids=["shown", "lower", "no-dash", "spaces", "dashes"],
)
def test_case_dashes_and_spaces_are_ignored(typed: str) -> None:
    code = InviteCode.parse(typed)

    assert code is not None
    assert code.display == "K7QM-4XPD"


def test_crockford_look_alikes_read_as_the_digit_they_resemble() -> None:
    code = InviteCode.parse("IlOo-ABCD")

    assert code is not None
    assert code.display == "1100-ABCD"


@pytest.mark.parametrize(
    "typed",
    ["", "K7QM-4XP", "K7QM-4XPDX", "K7QM-4XPU", "K7QM-4XP!", "K7QM_4XPD", "K7QM-4XPÉ"],
    ids=["empty", "seven", "nine", "U", "punctuation", "underscore", "accent"],
)
def test_anything_else_is_no_code(typed: str) -> None:
    assert InviteCode.parse(typed) is None


def test_the_hash_is_the_sha256_hex_of_the_eight_characters() -> None:
    code = InviteCode.parse("K7QM-4XPD")

    assert code is not None
    assert code.hash == hashlib.sha256(b"K7QM4XPD").hexdigest()
    assert DB_HASH_SHAPE.fullmatch(code.hash)


def test_a_code_typed_any_way_hashes_as_the_one_shown() -> None:
    shown = InviteCode.generate()
    typed = InviteCode.parse(shown.display.lower().replace("-", " "))

    assert typed is not None
    assert typed.hash == shown.hash


def test_the_hint_is_the_last_four_characters_and_fits_the_database() -> None:
    code = InviteCode.parse("K7QM-4XPD")

    assert code is not None
    assert code.hint == "4XPD"
    assert DB_HINT_SHAPE.fullmatch(code.hint)


def test_the_code_never_shows_in_its_repr() -> None:
    code = InviteCode.parse("K7QM-4XPD")

    assert "K7QM" not in repr(code)
    assert "4XPD" not in repr(code)


def test_a_code_lives_seven_days() -> None:
    assert CODE_LIFETIME == timedelta(days=7)
    assert IssuedCode.new(T0).expires_at == T0 + timedelta(days=7)


def test_a_code_is_live_until_the_moment_it_expires() -> None:
    issued = IssuedCode.new(T0)

    assert issued.is_live(T0)
    assert issued.is_live(issued.expires_at - timedelta(microseconds=1))
    assert not issued.is_live(issued.expires_at)


def test_a_revoked_code_is_not_live() -> None:
    issued = IssuedCode(expires_at=T0 + CODE_LIFETIME, revoked_at=T0)

    assert not issued.is_live(T0)


def test_a_redeemed_code_is_not_live() -> None:
    issued = IssuedCode(expires_at=T0 + CODE_LIFETIME, redeemed_at=T0)

    assert not issued.is_live(T0)


# --- why a code opens nothing (tasks.md K.4) -----------------------------------


def test_a_live_code_has_no_reason_to_be_dead() -> None:
    issued = IssuedCode.new(T0)

    assert issued.why_dead(issued.expires_at - timedelta(microseconds=1)) is None


@pytest.mark.parametrize(
    ("issued", "reason"),
    [
        (IssuedCode(expires_at=T0), DeadCode.EXPIRED),
        (IssuedCode(expires_at=T0 + CODE_LIFETIME, revoked_at=T0), DeadCode.REVOKED),
        (IssuedCode(expires_at=T0 + CODE_LIFETIME, redeemed_at=T0), DeadCode.SPENT),
        # What happened to it says more than the clock: it went before it expired.
        (IssuedCode(expires_at=T0, revoked_at=T0 - timedelta(days=1)), DeadCode.REVOKED),
        (IssuedCode(expires_at=T0, redeemed_at=T0 - timedelta(days=1)), DeadCode.SPENT),
    ],
)
def test_a_dead_code_says_why(issued: IssuedCode, reason: DeadCode) -> None:
    assert issued.why_dead(T0) is reason
    assert not issued.is_live(T0)


def test_ten_failed_attempts_in_the_window_are_the_limit() -> None:
    assert ATTEMPT_WINDOW == timedelta(hours=1)
    assert may_attempt(failures_in_window=MAX_FAILED_ATTEMPTS - 1)
    assert not may_attempt(failures_in_window=MAX_FAILED_ATTEMPTS)
    assert MAX_FAILED_ATTEMPTS == 10
