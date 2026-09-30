"""API tests for ``PUT`` and ``GET /api/credentials`` (tasks.md 6b.2, 6b.6; design 8a § C).

The PUT tests need no database: the router is mounted through ``create_app()``
(so the ``/api`` prefix and the bearer guard are part of what is proven) with
``get_save_credential`` overridden to a REAL ``SaveCredential`` over the fake
venue and writer of ``tests/accounts/fakes.py``. The fake venue records every
request, which is what makes "nothing was sent to the venue" an assertion.

The GET tests run against real PostgreSQL with the REAL vault, and use a cipher
that refuses to decrypt: the API process never decrypts (decision 5), so any
path that tried would fail loudly here.

Every key and secret is a sentinel (rule 1), and none is ever printed by an
assertion message.
"""

import ast
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.save_credential import SaveCredential, SaveOutcome
from strategy_manager.accounts.domain.errors import (
    ConcurrentCredentialSave,
    KeyRejected,
    VenueUnreachable,
)
from strategy_manager.accounts.domain.exchange_credential import (
    ExchangeCredential,
    KeyFacts,
)
from strategy_manager.accounts.domain.key_policy import PermissionSnapshot
from strategy_manager.accounts.infrastructure import credentials_router
from strategy_manager.accounts.infrastructure.capital_pool_writer import (
    SqlAlchemyCapitalPoolWriter,
)
from strategy_manager.accounts.infrastructure.credential_vault import SqlAlchemyCredentialVault
from strategy_manager.accounts.infrastructure.credentials_router import (
    OUTCOME_STATUS,
    get_save_credential,
)
from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.admin_auth import UNAUTHORIZED_DETAIL
from strategy_manager.shared.infrastructure.crypto import (
    MASTER_KEY_BYTES,
    Envelope,
    EnvelopeCipher,
)
from tests.accounts.fakes import (
    BINANCE_KEY,
    BINANCE_SECRET,
    BYBIT_KEY,
    BYBIT_SECRET,
    NOW,
    READ_ONLY_SNAPSHOT,
    TRADING_SNAPSHOT,
    TRANSFER_SNAPSHOT,
    RecordingCommit,
    RecordingInspector,
    RecordingPoolWriter,
    RecordingWriter,
    TickingClock,
    registry_for,
)
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)

TOKEN = "adm1n-t0ken"
WITHDRAWALS = "withdrawals_disabled_confirmed"
FUTURES = "futures_enabled_confirmed"

FACT_KEYS = {
    "validated_at",
    "trade_capable",
    "trade_capability_source",
    "trade_confirmed_at",
    "withdraw_check",
    "withdraw_confirmed_at",
    "internal_transfer",
}
ENTRY_KEYS = {"exchange", "status", "last4", "label", "stored_at"} | FACT_KEYS


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def _configure_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)


def _bybit_body(**over: Any) -> dict[str, Any]:
    return {"api_key": BYBIT_KEY, "api_secret": BYBIT_SECRET, **over}


def _binance_body(**over: Any) -> dict[str, Any]:
    return {"api_key": BINANCE_KEY, "api_secret": BINANCE_SECRET, **over}


def _use_case(
    inspector: RecordingInspector, writer: RecordingWriter, commit: RecordingCommit
) -> SaveCredential:
    return SaveCredential(
        registry_for(inspector), writer, RecordingPoolWriter(), commit, TickingClock()
    )


@dataclass
class Served:
    api: AsyncClient
    inspector: RecordingInspector
    writer: RecordingWriter
    commit: RecordingCommit


@asynccontextmanager
async def _serve(
    inspector: RecordingInspector | None = None, writer: RecordingWriter | None = None
) -> AsyncIterator[Served]:
    inspector = inspector or RecordingInspector(TRADING_SNAPSHOT)
    writer = writer or RecordingWriter()
    commit = RecordingCommit()
    app = create_app()
    use_case = _use_case(inspector, writer, commit)
    app.dependency_overrides[get_save_credential] = lambda: use_case
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        yield Served(api, inspector, writer, commit)


async def _put_bybit(served: "Served", **over: Any) -> Response:
    return await served.api.put(
        "/api/credentials/bybit", json=_bybit_body(**over), headers=_auth()
    )


def _assert_no_secret(text_: str) -> None:
    for sentinel in (BYBIT_KEY, BYBIT_SECRET, BINANCE_KEY, BINANCE_SECRET):
        assert sentinel not in text_


# --- PUT: the success answer ------------------------------------------------------------


async def test_put_credentials_returns_last4_and_facts_never_the_key_or_secret_or_a_raw_payload() -> (  # noqa: E501
    None
):
    async with _serve(RecordingInspector(TRANSFER_SNAPSHOT)) as served:
        response = await _put_bybit(served)

    assert response.status_code == 200
    assert response.json() == {
        "last4": BYBIT_KEY[-4:],
        "facts": {
            "validated_at": "2026-09-29T12:00:00Z",
            "trade_capable": True,
            "trade_capability_source": "VERIFIED",
            "trade_confirmed_at": None,
            "withdraw_check": "VERIFIED",
            "withdraw_confirmed_at": None,
            "internal_transfer": True,
        },
        "warnings": [],
    }
    _assert_no_secret(response.text)
    assert "permissions" not in response.text
    assert served.commit.commits == 1
    assert [credential.api_key for credential, _ in served.writer.stored] == [BYBIT_KEY]


async def test_put_a_read_only_bybit_key_is_stored_with_the_warning_and_trade_capable_false() -> (
    None
):
    async with _serve(RecordingInspector(READ_ONLY_SNAPSHOT)) as served:
        response = await _put_bybit(served)

    assert response.status_code == 200
    body = response.json()
    assert body["warnings"] == ["READ_ONLY_KEY"]
    assert body["facts"]["trade_capable"] is False
    _assert_no_secret(response.text)


async def test_put_a_binance_key_with_both_confirmations_is_stored_owner_confirmed_at_the_server_time() -> (  # noqa: E501
    None
):
    async with _serve(RecordingInspector(PermissionSnapshot())) as served:
        response = await served.api.put(
            "/api/credentials/binance",
            json=_binance_body(**{WITHDRAWALS: True, FUTURES: True}),
            headers=_auth(),
        )

    assert response.status_code == 200
    facts = response.json()["facts"]
    assert facts["trade_capability_source"] == "OWNER_CONFIRMED"
    assert facts["withdraw_check"] == "OWNER_CONFIRMED"
    # One clock reading: the same instant everywhere, UTC with a Z.
    assert facts["trade_confirmed_at"] == facts["withdraw_confirmed_at"] == facts["validated_at"]
    assert facts["validated_at"] == NOW.isoformat().replace("+00:00", "Z")
    _assert_no_secret(response.text)


async def test_put_the_label_is_optional_and_a_given_one_is_stored() -> None:
    async with _serve() as served:
        default = await _put_bybit(served)
        named = await served.api.put(
            "/api/credentials/bybit", json=_bybit_body(label="trading-2"), headers=_auth()
        )

    assert [default.status_code, named.status_code] == [200, 200]
    assert [credential.label for credential, _ in served.writer.stored] == ["default", "trading-2"]


# --- PUT: confirmations -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "missing"),
    [
        ({}, [WITHDRAWALS, FUTURES]),
        ({WITHDRAWALS: True}, [FUTURES]),
        ({FUTURES: True}, [WITHDRAWALS]),
        ({WITHDRAWALS: True, FUTURES: False}, [FUTURES]),
    ],
    ids=["neither", "only-withdrawals", "only-futures", "explicit-false"],
)
async def test_put_binance_missing_confirmation_422_names_the_missing_field(
    given: dict[str, bool], missing: list[str]
) -> None:
    async with _serve() as served:
        response = await served.api.put(
            "/api/credentials/binance", json=_binance_body(**given), headers=_auth()
        )

    assert response.status_code == 422
    body = response.json()
    assert body["outcome"] == "CONFIRMATION_REQUIRED"
    assert body["missing"] == missing
    assert set(body) == {"outcome", "detail", "missing"}
    # Before the venue: a key that cannot be stored is not worth a signed request.
    assert served.inspector.calls == []
    assert served.writer.stored == []
    assert served.commit.commits == 0
    _assert_no_secret(response.text)


@pytest.mark.parametrize("field", [WITHDRAWALS, FUTURES])
async def test_put_bybit_true_confirmation_422_not_applicable(field: str) -> None:
    async with _serve() as served:
        response = await served.api.put(
            "/api/credentials/bybit", json=_bybit_body(**{field: True}), headers=_auth()
        )

    assert response.status_code == 422
    body = response.json()
    assert body["outcome"] == "CONFIRMATION_NOT_APPLICABLE"
    assert field in body["detail"]
    assert "missing" not in body
    assert served.inspector.calls == []
    assert served.writer.stored == []


async def test_put_bybit_with_confirmations_false_is_fine() -> None:
    async with _serve() as served:
        response = await served.api.put(
            "/api/credentials/bybit",
            json=_bybit_body(**{WITHDRAWALS: False, FUTURES: False}),
            headers=_auth(),
        )

    assert response.status_code == 200


# --- PUT: the outcome-to-HTTP map -----------------------------------------------------------

_WITHDRAW_SNAPSHOT = PermissionSnapshot(wallet_permissions=frozenset({"Withdraw"}), read_only=False)
_UNAVAILABLE_SNAPSHOT = PermissionSnapshot(wallet_permissions=None, read_only=None)

#: (expected outcome, expected status, inspector, writer)
REFUSALS: list[tuple[SaveOutcome, int, RecordingInspector, RecordingWriter]] = [
    (
        SaveOutcome.KEY_REJECTED,
        422,
        RecordingInspector(error=KeyRejected("bybit rejected the key (retCode 10003)")),
        RecordingWriter(),
    ),
    (
        SaveOutcome.VENUE_UNREACHABLE,
        502,
        RecordingInspector(error=VenueUnreachable("bybit answered HTTP 503")),
        RecordingWriter(),
    ),
    (
        SaveOutcome.WITHDRAW_PERMISSION,
        422,
        RecordingInspector(_WITHDRAW_SNAPSHOT),
        RecordingWriter(),
    ),
    (
        SaveOutcome.PERMISSIONS_UNAVAILABLE,
        422,
        RecordingInspector(_UNAVAILABLE_SNAPSHOT),
        RecordingWriter(),
    ),
    (
        SaveOutcome.CONCURRENT_SAVE,
        409,
        RecordingInspector(TRADING_SNAPSHOT),
        RecordingWriter(error=ConcurrentCredentialSave("another save was stored first")),
    ),
]


@pytest.mark.parametrize(
    ("outcome", "status", "inspector", "writer"),
    REFUSALS,
    ids=[refusal[0].value for refusal in REFUSALS],
)
async def test_put_each_refusal_maps_to_its_status_with_one_body_shape(
    outcome: SaveOutcome, status: int, inspector: RecordingInspector, writer: RecordingWriter
) -> None:
    async with _serve(inspector, writer) as served:
        response = await _put_bybit(served)

    assert response.status_code == status
    body = response.json()
    assert set(body) == {"outcome", "detail"}
    assert body["outcome"] == outcome.value
    assert body["detail"]
    assert writer.stored == []
    assert served.commit.commits == 0
    _assert_no_secret(response.text)


def test_the_outcome_map_covers_every_save_outcome_and_only_saved_is_a_success() -> None:
    assert set(OUTCOME_STATUS) == set(SaveOutcome) - {SaveOutcome.SAVED}
    assert OUTCOME_STATUS[SaveOutcome.VENUE_UNREACHABLE] == 502
    assert OUTCOME_STATUS[SaveOutcome.CONCURRENT_SAVE] == 409
    assert {
        status for outcome, status in OUTCOME_STATUS.items()
    } == {409, 422, 502}


async def test_put_an_unserved_exchange_is_404_and_nothing_is_sent_to_any_venue() -> None:
    async with _serve() as served:
        response = await served.api.put(
            "/api/credentials/pionex", json=_bybit_body(), headers=_auth()
        )

    assert response.status_code == 404
    assert "pionex" in response.json()["detail"]
    assert served.inspector.calls == []
    assert served.writer.stored == []
    _assert_no_secret(response.text)


# --- PUT: the body ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    ["validated_at", "trade_confirmed_at", "withdraw_confirmed_at", "trade_capable"],
)
async def test_put_a_client_cannot_supply_a_confirmation_time_or_a_fact(extra: str) -> None:
    async with _serve() as served:
        response = await served.api.put(
            "/api/credentials/bybit",
            json=_bybit_body(**{extra: "2020-01-01T00:00:00Z"}),
            headers=_auth(),
        )

    assert response.status_code == 422
    assert served.inspector.calls == []
    assert served.writer.stored == []


@pytest.mark.parametrize(
    "body",
    [
        {"api_key": BYBIT_KEY, "api_secret": {"nested": BYBIT_SECRET}},
        {"api_key": [BYBIT_KEY], "api_secret": BYBIT_SECRET},
        {"api_key": BYBIT_KEY},
        {"api_key": "abc", "api_secret": BYBIT_SECRET},
        {"api_key": BYBIT_KEY, "api_secret": BYBIT_SECRET, "surprise": BYBIT_SECRET},
    ],
    ids=["secret-as-object", "key-as-list", "missing-secret", "key-too-short", "extra-field"],
)
async def test_put_a_bad_body_is_a_422_that_echoes_neither_key_nor_secret(
    body: dict[str, Any],
) -> None:
    async with _serve() as served:
        response = await served.api.put("/api/credentials/bybit", json=body, headers=_auth())

    assert response.status_code == 422
    assert response.json()["detail"], "a 422 with no errors would prove nothing"
    _assert_no_secret(response.text)
    assert served.inspector.calls == []
    assert served.writer.stored == []


async def test_put_a_malformed_json_body_is_a_422_that_echoes_nothing() -> None:
    async with _serve() as served:
        response = await served.api.put(
            "/api/credentials/bybit",
            content='{"api_key": "' + BYBIT_KEY + '", "api_secret": "' + BYBIT_SECRET,
            headers={**_auth(), "Content-Type": "application/json"},
        )

    assert response.status_code == 422
    _assert_no_secret(response.text)


#: Hostile values: none may reach the venue, the store, a response or a log.
_HOSTILE = {
    "non-ascii": "KéééYYYY",
    "space": "AAAA BBBB",
    "trailing-space": "AAAABBBB ",
    "tab": "AAAA\tBBBB",
    "newline": "AAAA\nBBBB",
    "too-long": "A" * 257,
}


@pytest.mark.parametrize("field", ["api_key", "api_secret"])
@pytest.mark.parametrize("value", list(_HOSTILE.values()), ids=list(_HOSTILE))
async def test_put_a_key_or_secret_outside_printable_ascii_or_over_256_is_a_422_and_never_stored(
    field: str, value: str, caplog: pytest.LogCaptureFixture
) -> None:
    async with _serve() as served:
        with caplog.at_level("DEBUG"):
            response = await _put_bybit(served, **{field: value})

    assert response.status_code == 422
    assert response.json()["detail"], "a 422 with no errors would prove nothing"
    assert served.inspector.calls == []
    assert served.writer.stored == []
    assert served.commit.commits == 0
    assert value not in response.text
    assert value not in caplog.text
    assert repr(value) not in response.text + caplog.text


@pytest.mark.parametrize("field", ["api_key", "api_secret"])
async def test_put_exactly_256_printable_ascii_characters_is_accepted(field: str) -> None:
    value = "".join(chr(0x21 + i % 94) for i in range(256))
    async with _serve() as served:
        response = await _put_bybit(served, **{field: value})

    assert response.status_code == 200
    assert len(served.writer.stored) == 1
    assert value not in response.text


def test_the_credential_body_never_shows_the_secret_in_its_repr() -> None:
    body = credentials_router.CredentialBody(api_key=BYBIT_KEY, api_secret=BYBIT_SECRET)  # type: ignore[arg-type]
    assert BYBIT_SECRET not in repr(body)
    assert BYBIT_SECRET not in str(body)


# --- Cache-Control: no-store on every credentials response -------------------------------


def _assert_no_store(response: Response) -> None:
    assert response.headers.get("cache-control") == "no-store"


async def test_every_put_answer_carries_no_store() -> None:
    answers: dict[str, Response] = {}
    async with _serve() as served:
        answers["200"] = await _put_bybit(served)
        answers["422-validation"] = await _put_bybit(served, api_key="abc")
        answers["422-malformed"] = await served.api.put(
            "/api/credentials/bybit",
            content="{not json",
            headers={**_auth(), "Content-Type": "application/json"},
        )
        answers["422-refusal"] = await _put_bybit(served, **{WITHDRAWALS: True})
        answers["401-missing"] = await served.api.put(
            "/api/credentials/bybit", json=_bybit_body()
        )
        answers["401-wrong"] = await served.api.put(
            "/api/credentials/bybit",
            json=_bybit_body(),
            headers={"Authorization": "Bearer not-the-token"},
        )
        answers["404"] = await served.api.put(
            "/api/credentials/pionex", json=_bybit_body(), headers=_auth()
        )
    for outcome, status in (
        (SaveOutcome.CONCURRENT_SAVE, 409),
        (SaveOutcome.VENUE_UNREACHABLE, 502),
    ):
        refusal = next(r for r in REFUSALS if r[0] == outcome)
        async with _serve(refusal[2], refusal[3]) as served:
            answers[str(status)] = await _put_bybit(served)

    assert {k: v.status_code for k, v in answers.items()} == {
        "200": 200,
        "422-validation": 422,
        "422-malformed": 422,
        "422-refusal": 422,
        "401-missing": 401,
        "401-wrong": 401,
        "404": 404,
        "409": 409,
        "502": 502,
    }
    without = [k for k, v in answers.items() if v.headers.get("cache-control") != "no-store"]
    assert without == []


async def test_a_get_refused_for_its_token_carries_no_store() -> None:
    async with _serve() as served:
        missing = await served.api.get("/api/credentials")
        wrong = await served.api.get(
            "/api/credentials", headers={"Authorization": "Bearer not-the-token"}
        )

    assert [missing.status_code, wrong.status_code] == [401, 401]
    _assert_no_store(missing)
    _assert_no_store(wrong)


async def test_the_503_for_an_unusable_master_key_carries_no_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "master_encryption_key", "")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        response = await api.put("/api/credentials/bybit", json=_bybit_body(), headers=_auth())

    assert response.status_code == 503
    _assert_no_store(response)


async def test_no_store_is_scoped_to_the_credentials_routes() -> None:
    async with _serve() as served:
        health = await served.api.get("/health")

    assert health.status_code == 200
    assert "cache-control" not in health.headers


# --- auth ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"), [("PUT", "/api/credentials/bybit"), ("GET", "/api/credentials")]
)
async def test_the_credential_routes_refuse_a_missing_or_wrong_token(
    method: str, path: str
) -> None:
    async with _serve() as served:
        body = _bybit_body() if method == "PUT" else None
        missing = await served.api.request(method, path, json=body)
        wrong = await served.api.request(
            method, path, json=body, headers={"Authorization": "Bearer not-the-token"}
        )

    assert [missing.status_code, wrong.status_code] == [401, 401]
    assert missing.json() == wrong.json() == {"detail": UNAUTHORIZED_DETAIL}
    assert served.inspector.calls == []
    assert served.writer.stored == []


# --- the real dependency ------------------------------------------------------------------


async def test_an_unusable_master_key_answers_503_before_anything_else_and_says_why_in_the_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(get_settings(), "master_encryption_key", "")
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        with caplog.at_level("DEBUG"):
            response = await api.put("/api/credentials/bybit", json=_bybit_body(), headers=_auth())

    assert response.status_code == 503
    assert response.json() == {"detail": "credential storage is not configured"}
    errors = [record for record in caplog.records if record.levelname == "ERROR"]
    assert len(errors) == 1
    assert "MASTER_ENCRYPTION_KEY" in errors[0].getMessage()
    _assert_no_secret(response.text + caplog.text)


# --- GET: real PostgreSQL, the real vault, a cipher that will not decrypt ---------------------


class _NeverDecrypts(EnvelopeCipher):
    """The API process never decrypts (decision 5)."""

    def unseal(self, envelope: Envelope, context: str) -> dict[str, str]:
        raise AssertionError("the credentials API tried to decrypt")


def _cipher() -> EnvelopeCipher:
    return _NeverDecrypts(os.urandom(MASTER_KEY_BYTES))


@pytest.fixture
async def factory(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> async_sessionmaker[AsyncSession]:
    """The test database with no credential rows left by another test."""
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE exchange_credentials CASCADE"))
        await session.commit()
    return pg_session_factory


@asynccontextmanager
async def _serve_db(
    factory: async_sessionmaker[AsyncSession], inspector: RecordingInspector | None = None
) -> AsyncIterator[Served]:
    inspector = inspector or RecordingInspector(TRANSFER_SNAPSHOT)
    cipher = _cipher()
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    async def _use_case_over_the_real_vault(
        session: Annotated[AsyncSession, Depends(shared_db.get_session)],
    ) -> SaveCredential:
        clock = TickingClock()
        return SaveCredential(
            registry_for(inspector),
            SqlAlchemyCredentialVault(session, cipher, clock),
            SqlAlchemyCapitalPoolWriter(session),
            session,
            clock,
        )

    app.dependency_overrides[shared_db.get_session] = _session
    app.dependency_overrides[get_save_credential] = _use_case_over_the_real_vault
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        yield Served(api, inspector, RecordingWriter(), RecordingCommit())


async def _set_pool_enabled(
    factory: async_sessionmaker[AsyncSession], exchange: str, enabled: bool
) -> None:
    async with factory() as session:
        await session.execute(
            text("UPDATE capital_pools SET enabled = :enabled WHERE exchange = :exchange"),
            {"enabled": enabled, "exchange": exchange},
        )
        await session.commit()


def _entry(entries: list[dict[str, Any]], exchange: str) -> dict[str, Any]:
    found = [entry for entry in entries if entry["exchange"] == exchange]
    assert len(found) == 1, f"expected exactly one {exchange} entry, got {len(found)}"
    return found[0]


@pytest.mark.integration
async def test_get_credentials_shows_source_and_confirmation_fields_never_live_requery(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with _serve_db(factory, RecordingInspector(PermissionSnapshot())) as served:
        saved = await served.api.put(
            "/api/credentials/binance",
            json=_binance_body(**{WITHDRAWALS: True, FUTURES: True}),
            headers=_auth(),
        )
        assert saved.status_code == 200
        calls_after_save = list(served.inspector.calls)

        listed = await served.api.get("/api/credentials", headers=_auth())

    assert listed.status_code == 200
    _assert_no_store(saved)
    _assert_no_store(listed)
    entry = _entry(listed.json(), "binance")
    assert entry == {
        "exchange": "binance",
        "status": "STORED",
        "last4": BINANCE_KEY[-4:],
        "label": "default",
        "stored_at": entry["stored_at"],
        "validated_at": "2026-09-29T12:00:00Z",
        "trade_capable": True,
        "trade_capability_source": "OWNER_CONFIRMED",
        "trade_confirmed_at": "2026-09-29T12:00:00Z",
        "withdraw_check": "OWNER_CONFIRMED",
        "withdraw_confirmed_at": "2026-09-29T12:00:00Z",
        "internal_transfer": None,
    }
    assert entry["stored_at"].endswith("Z")
    # The listing reads the snapshot only: no second venue request, and the
    # cipher above would have raised on any decrypt.
    assert served.inspector.calls == calls_after_save == ["binance"]
    _assert_no_secret(listed.text)


@pytest.mark.integration
async def test_get_credentials_entries_have_no_permissions_key(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with _serve_db(factory) as served:
        await served.api.put("/api/credentials/bybit", json=_bybit_body(), headers=_auth())
        listed = await served.api.get("/api/credentials", headers=_auth())

    entries = listed.json()
    assert {entry["exchange"] for entry in entries} >= {"bybit"}
    for entry in entries:
        assert set(entry) == ENTRY_KEYS, entry["exchange"]
        assert "permissions" not in entry
    assert "permissions" not in listed.text
    assert "ciphertext" not in listed.text.lower()


@pytest.mark.integration
async def test_get_credentials_an_exchange_with_only_an_enabled_pool_is_empty_and_all_null(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with _serve_db(factory) as served:
        listed = await served.api.get("/api/credentials", headers=_auth())

    entries = listed.json()
    # The seeded pools are pionex and bybit, all enabled, and nothing is stored.
    assert sorted(entry["exchange"] for entry in entries) == ["bybit", "pionex"]
    for entry in entries:
        assert entry["status"] == "EMPTY"
        nulled = {k: v for k, v in entry.items() if k not in {"exchange", "status"}}
        assert nulled == {key: None for key in ENTRY_KEYS - {"exchange", "status"}}


@pytest.mark.integration
async def test_get_credentials_an_exchange_with_only_a_history_row_is_listed_empty(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        vault = SqlAlchemyCredentialVault(session, _cipher(), TickingClock())
        await vault.store(
            ExchangeCredential(
                exchange="binance", label="default", api_key=BINANCE_KEY, api_secret=BINANCE_SECRET
            ),
            KeyFacts.unrecorded(trade_capable=True),
        )
        await session.execute(
            text("UPDATE exchange_credentials SET is_active = false WHERE exchange = 'binance'")
        )
        await session.commit()
    await _set_pool_enabled(factory, "bybit", False)
    await _set_pool_enabled(factory, "pionex", False)

    async with _serve_db(factory) as served:
        listed = await served.api.get("/api/credentials", headers=_auth())

    entries = listed.json()
    # Binance has no pool at all, no active key, and one superseded row.
    assert [entry["exchange"] for entry in entries] == ["binance"]
    assert entries[0]["status"] == "EMPTY"
    assert entries[0]["last4"] is None
    assert entries[0]["label"] is None
    _assert_no_secret(listed.text)


@pytest.mark.integration
async def test_get_credentials_an_exchange_with_no_key_no_history_and_no_enabled_pool_is_absent(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _set_pool_enabled(factory, "bybit", False)

    async with _serve_db(factory) as served:
        listed = await served.api.get("/api/credentials", headers=_auth())

    assert [entry["exchange"] for entry in listed.json()] == ["pionex"]


@pytest.mark.integration
async def test_get_credentials_a_rotated_exchange_is_one_entry_the_active_key(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    first, second = "FIRST-BYBIT-KEY-1111", "SECOND-BYBIT-KEY-2222"
    async with _serve_db(factory) as served:
        one = await served.api.put(
            "/api/credentials/bybit", json=_bybit_body(api_key=first), headers=_auth()
        )
        two = await served.api.put(
            "/api/credentials/bybit", json=_bybit_body(api_key=second), headers=_auth()
        )
        listed = await served.api.get("/api/credentials", headers=_auth())

    assert [one.status_code, two.status_code] == [200, 200]
    entry = _entry(listed.json(), "bybit")
    assert entry["status"] == "STORED"
    assert entry["last4"] == second[-4:]
    assert first not in listed.text and second not in listed.text


@pytest.mark.integration
async def test_get_credentials_a_legacy_row_reads_unrecorded_with_no_validation_time(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        vault = SqlAlchemyCredentialVault(session, _cipher(), TickingClock())
        await vault.store(
            ExchangeCredential(
                exchange="pionex", label="default", api_key="PIONEX-KEY-9999", api_secret="x-secret"
            ),
            KeyFacts.unrecorded(trade_capable=True),
        )
        await session.commit()

    async with _serve_db(factory) as served:
        listed = await served.api.get("/api/credentials", headers=_auth())

    entry = _entry(listed.json(), "pionex")
    assert entry["status"] == "STORED"
    assert entry["last4"] == "9999"
    assert entry["trade_capable"] is True
    assert entry["trade_capability_source"] == "UNRECORDED"
    assert entry["withdraw_check"] == "UNRECORDED"
    assert entry["validated_at"] is None
    assert entry["trade_confirmed_at"] is None
    assert entry["withdraw_confirmed_at"] is None


# --- the router never decrypts --------------------------------------------------------------


def test_the_listing_module_cannot_reach_a_secret_column_or_the_cipher() -> None:
    """The listing selects the columns it shows. It names no ciphertext column and
    imports no cipher, so a later edit cannot start returning what it cannot see."""
    source = Path(credentials_router.__file__).with_name("credential_listing.py").read_text("utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom | ast.Import)
        for alias in node.names
    }
    assert "EnvelopeCipher" not in imported
    assert "ciphertext" not in source
    assert "nonce" not in source
    assert "wrapped_dek" not in source
