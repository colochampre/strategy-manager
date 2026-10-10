"""Cross-language guard: the panel's list of served exchanges equals the server's tables.

The Settings page of the operator panel cannot learn from either read route
which exchanges it manages a key for (an exchange with no row is in neither),
nor which confirmations a key form must ask for (the API says that only by
refusing). So the panel keeps one small file,
``frontend/src/shared/credentials/served-exchanges.json``, and THIS test is
what keeps it equal to the two server tables it mirrors:

* the file's exchanges are exactly the keys of ``KNOWN_FUTURES_POOLS`` and of
  ``KEY_POLICIES``;
* an exchange lists confirmations exactly when its policy is
  ``OWNER_CONFIRMED``, and then exactly ``WITHDRAWALS_CONFIRMATION`` and
  ``FUTURES_CONFIRMATION``.

The comparison is a small function of this module, and two tests feed it
tables that have drifted, so the gate's failure is itself tested: a guard that
cannot fail is not a guard. The same device already guards the webhook message
(``tests/signals/domain/test_webhook_message_fixture.py``).

This test only READS the file. It never writes it.
"""

import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

from strategy_manager.accounts.domain.key_policy import (
    FUTURES_CONFIRMATION,
    KEY_POLICIES,
    WITHDRAWALS_CONFIRMATION,
    PolicyBasis,
)
from strategy_manager.accounts.domain.known_pools import KNOWN_FUTURES_POOLS, KnownPool
from strategy_manager.shared.domain.money import Currency, Exchange, Venue

_REPO_ROOT = Path(__file__).resolve().parents[4]
_FIXTURE = _REPO_ROOT / "frontend" / "src" / "shared" / "credentials" / "served-exchanges.json"


def _read_fixture() -> Any:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _drift(
    served: Mapping[str, Any],
    pools: Mapping[Exchange, KnownPool],
    policies: Mapping[str, PolicyBasis],
) -> list[str]:
    """Every way the file and the two tables disagree; empty when they agree."""
    problems: list[str] = []
    file_exchanges = set(served)
    pool_exchanges = {exchange.value for exchange in pools}
    policy_exchanges = set(policies)

    if file_exchanges != pool_exchanges:
        problems.append(
            f"the file lists {sorted(file_exchanges)} but KNOWN_FUTURES_POOLS holds "
            f"{sorted(pool_exchanges)}"
        )
    if file_exchanges != policy_exchanges:
        problems.append(
            f"the file lists {sorted(file_exchanges)} but KEY_POLICIES holds "
            f"{sorted(policy_exchanges)}"
        )

    for exchange in sorted(file_exchanges & policy_exchanges):
        expected = (
            [WITHDRAWALS_CONFIRMATION, FUTURES_CONFIRMATION]
            if policies[exchange] is PolicyBasis.OWNER_CONFIRMED
            else []
        )
        listed = served[exchange]["confirmations"]
        # Sorted, so a duplicate shows as a longer list and the display order
        # is the panel's to choose.
        if sorted(listed) != sorted(expected):
            problems.append(
                f"{exchange} lists confirmations {listed} but its policy "
                f"{policies[exchange].value} requires {expected}"
            )
    return problems


def test_the_files_exchanges_equal_the_keys_of_known_futures_pools_and_of_key_policies() -> None:
    served = _read_fixture()

    assert set(served) == {exchange.value for exchange in KNOWN_FUTURES_POOLS}
    assert set(served) == set(KEY_POLICIES)
    assert _drift(served, KNOWN_FUTURES_POOLS, KEY_POLICIES) == []


def test_an_exchange_lists_confirmations_exactly_when_its_policy_is_owner_confirmed() -> None:
    served = _read_fixture()

    owner_confirmed = [
        exchange for exchange, basis in KEY_POLICIES.items() if basis is PolicyBasis.OWNER_CONFIRMED
    ]
    assert owner_confirmed, "KEY_POLICIES needs an owner-confirmed exchange or this proves nothing"
    for exchange in owner_confirmed:
        assert exchange in served, f"the file does not list {exchange}"
        listed = served[exchange]["confirmations"]
        assert len(listed) == 2
        assert set(listed) == {WITHDRAWALS_CONFIRMATION, FUTURES_CONFIRMATION}

    verified = [
        exchange
        for exchange, basis in KEY_POLICIES.items()
        if basis is not PolicyBasis.OWNER_CONFIRMED
    ]
    assert verified, "the table must hold a server-verified exchange, or this proves nothing"
    for exchange in verified:
        assert exchange in served, f"the file does not list {exchange}"
        assert served[exchange]["confirmations"] == []


def test_a_third_exchange_in_a_table_is_a_drift() -> None:
    served = _read_fixture()
    pools_with_pionex = {
        **KNOWN_FUTURES_POOLS,
        Exchange.PIONEX: KnownPool(Venue.USDT_M, Currency.USDT, Decimal("5")),
    }
    policies_with_pionex = {**KEY_POLICIES, "pionex": PolicyBasis.SERVER_VERIFIED}

    # The honest tables agree with the file, so a report below is the drift's.
    assert _drift(served, KNOWN_FUTURES_POOLS, KEY_POLICIES) == []
    assert _drift(served, pools_with_pionex, KEY_POLICIES) != []
    assert _drift(served, KNOWN_FUTURES_POOLS, policies_with_pionex) != []


def test_a_changed_policy_is_a_drift() -> None:
    served = _read_fixture()
    bybit_now_owner_confirmed = {**KEY_POLICIES, "bybit": PolicyBasis.OWNER_CONFIRMED}
    binance_now_verified = {**KEY_POLICIES, "binance": PolicyBasis.SERVER_VERIFIED}

    assert _drift(served, KNOWN_FUTURES_POOLS, KEY_POLICIES) == []
    assert _drift(served, KNOWN_FUTURES_POOLS, bybit_now_owner_confirmed) != []
    assert _drift(served, KNOWN_FUTURES_POOLS, binance_now_verified) != []


def test_the_file_is_an_object_of_exchanges_each_with_a_list_of_strings() -> None:
    served = _read_fixture()

    assert isinstance(served, dict)
    assert served, "an empty object serves no exchange"
    for exchange, entry in served.items():
        assert isinstance(exchange, str)
        assert exchange
        assert isinstance(entry, dict)
        assert set(entry) == {"confirmations"}
        assert isinstance(entry["confirmations"], list)
        assert all(isinstance(name, str) for name in entry["confirmations"])
