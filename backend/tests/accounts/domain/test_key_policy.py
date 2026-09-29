"""``key_policy`` -- owner decisions 24 and 30, design addendum sections A and D.

Bybit is verified server-side: the snapshot carries ``permissions.Wallet`` and
``readOnly``. Binance cannot be inspected for either, so its snapshot is empty
and its facts are owner-confirmed. The two never mix.

Fixtures come from the shapes probes P1 and P2 recorded (tasks.md, "PR 1 --
Probe results"), never from a real payload: the vault key lists
``['AccountTransfer', 'SubMemberTransfer']`` and reads ``readOnly=0``; the
read-only key still lists ``ContractTrade`` and ``Derivatives``.
"""

import ast
import dataclasses
import inspect
from pathlib import Path

import pytest

from strategy_manager.accounts.domain import key_policy
from strategy_manager.accounts.domain.exchange_credential import FactSource
from strategy_manager.accounts.domain.key_policy import (
    FUTURES_CONFIRMATION,
    KEY_POLICIES,
    WITHDRAWALS_CONFIRMATION,
    KeyAccepted,
    KeyRefused,
    OwnerConfirmations,
    PermissionSnapshot,
    RefusalOutcome,
    UnservedExchange,
    check_confirmations,
    evaluate_key,
)
from strategy_manager.shared.domain.errors import InvariantViolation

NONE = OwnerConfirmations()
BOTH = OwnerConfirmations(withdrawals_disabled=True, futures_enabled=True)

# P1: what the vault's Bybit key lists under permissions.Wallet.
VAULT_WALLET = frozenset({"AccountTransfer", "SubMemberTransfer"})


def _bybit(
    wallet: frozenset[str] | None = VAULT_WALLET, read_only: bool | None = False
) -> PermissionSnapshot:
    return PermissionSnapshot(wallet_permissions=wallet, read_only=read_only)


def _accepted(verdict: object) -> KeyAccepted:
    assert isinstance(verdict, KeyAccepted), verdict
    return verdict


def _refused(verdict: object) -> KeyRefused:
    assert isinstance(verdict, KeyRefused), verdict
    return verdict


# --- withdraw side (6a.1) ---------------------------------------------------


def test_evaluate_key_refuses_withdraw_permission_bybit_wallet_withdraw() -> None:
    wallet = frozenset({"Withdraw", "AccountTransfer"})

    refusal = _refused(evaluate_key("bybit", _bybit(wallet=wallet), NONE))

    assert refusal.outcome is RefusalOutcome.WITHDRAW_PERMISSION
    assert "Withdraw" in refusal.detail
    # Names the offending token, not the ones that were fine.
    assert "AccountTransfer" not in refusal.detail


def test_evaluate_key_allows_internal_transfer_only_accounttransfer() -> None:
    verdict = _accepted(
        evaluate_key("bybit", _bybit(wallet=frozenset({"AccountTransfer"})), NONE)
    )

    assert verdict.withdraw_check is FactSource.VERIFIED
    assert verdict.internal_transfer is True


def test_evaluate_key_bybit_without_accounttransfer_reports_internal_transfer_false() -> None:
    verdict = _accepted(evaluate_key("bybit", _bybit(wallet=frozenset()), NONE))

    assert verdict.internal_transfer is False
    assert verdict.withdraw_check is FactSource.VERIFIED


def test_evaluate_key_bybit_wallet_token_outside_the_transfer_allowlist_refused_fail_closed() -> (
    None
):
    """A token nobody has seen is refused, not waved through: fail-closed."""
    wallet = frozenset({"AccountTransfer", "SomethingNew"})

    refusal = _refused(evaluate_key("bybit", _bybit(wallet=wallet), NONE))

    assert refusal.outcome is RefusalOutcome.WITHDRAW_PERMISSION
    assert "SomethingNew" in refusal.detail


def test_evaluate_key_bybit_missing_or_non_list_wallet_refused_permissions_unavailable() -> None:
    # The inspector maps a missing or non-list ``Wallet`` to ``None``.
    refusal = _refused(evaluate_key("bybit", _bybit(wallet=None), NONE))

    assert refusal.outcome is RefusalOutcome.PERMISSIONS_UNAVAILABLE


def test_evaluate_key_bybit_missing_read_only_refused_permissions_unavailable() -> None:
    refusal = _refused(evaluate_key("bybit", _bybit(read_only=None), NONE))

    assert refusal.outcome is RefusalOutcome.PERMISSIONS_UNAVAILABLE


@pytest.mark.parametrize(
    ("confirmations", "field"),
    [
        (OwnerConfirmations(withdrawals_disabled=True), WITHDRAWALS_CONFIRMATION),
        (OwnerConfirmations(futures_enabled=True), FUTURES_CONFIRMATION),
    ],
)
def test_evaluate_key_bybit_confirmation_true_refused_confirmation_not_applicable(
    confirmations: OwnerConfirmations, field: str
) -> None:
    """Refused, not ignored: a confirmation the server silently drops leaves
    the owner believing one was recorded."""
    refusal = _refused(evaluate_key("bybit", _bybit(), confirmations))

    assert refusal.outcome is RefusalOutcome.CONFIRMATION_NOT_APPLICABLE
    assert field in refusal.detail
    assert check_confirmations("bybit", confirmations) == refusal


_MISSING_CASES = [
    (NONE, (WITHDRAWALS_CONFIRMATION, FUTURES_CONFIRMATION)),
    (OwnerConfirmations(futures_enabled=True), (WITHDRAWALS_CONFIRMATION,)),
    (OwnerConfirmations(withdrawals_disabled=True), (FUTURES_CONFIRMATION,)),
]


@pytest.mark.parametrize(("confirmations", "missing"), _MISSING_CASES)
def test_evaluate_key_binance_without_both_confirmations_refused_confirmation_required_naming_missing(  # noqa: E501
    confirmations: OwnerConfirmations, missing: tuple[str, ...]
) -> None:
    refusal = _refused(evaluate_key("binance", PermissionSnapshot(), confirmations))

    assert refusal.outcome is RefusalOutcome.CONFIRMATION_REQUIRED
    assert refusal.missing == missing
    # ``check_confirmations`` is what runs BEFORE any venue call, and it must
    # refuse exactly the same way.
    assert check_confirmations("binance", confirmations) == refusal


def test_check_confirmations_accepts_what_the_venue_call_may_follow() -> None:
    assert check_confirmations("binance", BOTH) is None
    assert check_confirmations("bybit", NONE) is None


def test_evaluate_key_binance_with_both_confirmations_accepted_withdraw_check_owner_confirmed_never_verified() -> (  # noqa: E501
    None
):
    verdict = _accepted(evaluate_key("binance", PermissionSnapshot(), BOTH))

    assert verdict.withdraw_check is FactSource.OWNER_CONFIRMED
    assert verdict.trade_capability_source is FactSource.OWNER_CONFIRMED
    assert FactSource.VERIFIED not in (verdict.withdraw_check, verdict.trade_capability_source)
    assert verdict.internal_transfer is None
    assert verdict.warnings == ()


def test_evaluate_key_binance_snapshot_with_observed_fields_is_a_programming_error() -> None:
    """A Binance snapshot is empty by construction. One that is not means the
    inspector or the caller took the wrong branch, and the alternative is
    quietly trusting a fact the venue cannot have supplied."""
    with pytest.raises(InvariantViolation):
        evaluate_key("binance", _bybit(), BOTH)


def test_evaluate_key_unserved_exchange_raises_no_fallback() -> None:
    with pytest.raises(UnservedExchange):
        evaluate_key("kraken", PermissionSnapshot(), BOTH)
    with pytest.raises(UnservedExchange):
        check_confirmations("kraken", BOTH)


def test_key_policies_serve_exactly_bybit_and_binance() -> None:
    assert set(KEY_POLICIES) == {"bybit", "binance"}


# --- trade side (6a.2) ------------------------------------------------------


def test_evaluate_key_bybit_readonly_zero_trade_capable_true_source_verified() -> None:
    verdict = _accepted(evaluate_key("bybit", _bybit(read_only=False), NONE))

    assert verdict.trade_capable is True
    assert verdict.trade_capability_source is FactSource.VERIFIED
    assert verdict.warnings == ()


def test_evaluate_key_bybit_readonly_one_trade_capable_false_verified_warning_read_only_key() -> (
    None
):
    """The P2 read-only key still lists ContractTrade and Derivatives, but the
    snapshot cannot carry them; ``readOnly`` alone decides."""
    verdict = _accepted(evaluate_key("bybit", _bybit(read_only=True), NONE))

    assert verdict.trade_capable is False
    assert verdict.trade_capability_source is FactSource.VERIFIED
    assert verdict.warnings == ("READ_ONLY_KEY",)


def test_evaluate_key_bybit_never_reads_the_permission_lists_for_trade_capability() -> None:
    assert {f.name for f in dataclasses.fields(PermissionSnapshot)} == {
        "wallet_permissions",
        "read_only",
    }
    tree = ast.parse(Path(inspect.getsourcefile(key_policy) or "").read_text(encoding="utf-8"))
    # The module docstring names canTrade/canWithdraw to say why they are
    # absent. Everything else must not mention any of these.
    tree.body = tree.body[1:]
    code = ast.unparse(tree)
    for token in ("canTrade", "canWithdraw", "ContractTrade", "Derivatives"):
        assert token not in code


def test_evaluate_key_binance_trade_capable_true_source_owner_confirmed_from_the_futures_confirmation() -> (  # noqa: E501
    None
):
    verdict = _accepted(evaluate_key("binance", PermissionSnapshot(), BOTH))

    assert verdict.trade_capable is True
    assert verdict.trade_capability_source is FactSource.OWNER_CONFIRMED
