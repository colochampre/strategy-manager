"""``EnvelopeCipher`` — envelope encryption for secrets at rest.

The tests that matter are the ones proving a ciphertext cannot be reused
somewhere it does not belong. Confidentiality is what AES gives you for free;
binding a value to its own slot is what stops a database with write access
from swapping one credential's secret into another's row.
"""

import base64
import os

import pytest

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.crypto import (
    MASTER_KEY_BYTES,
    DecryptionFailed,
    EnvelopeCipher,
    SealedValue,
)

CONTEXT = "exchange_credentials/11111111-1111-1111-1111-111111111111"
OTHER_CONTEXT = "exchange_credentials/22222222-2222-2222-2222-222222222222"
SECRETS = {"api_key": "PIONEX-KEY-VALUE", "api_secret": "PIONEX-SECRET-VALUE"}


@pytest.fixture
def master_key() -> bytes:
    return os.urandom(MASTER_KEY_BYTES)


@pytest.fixture
def cipher(master_key: bytes) -> EnvelopeCipher:
    return EnvelopeCipher(master_key)


def test_a_sealed_envelope_opens_back_to_the_same_plaintexts(
    cipher: EnvelopeCipher,
) -> None:
    envelope = cipher.seal(SECRETS, CONTEXT)

    assert cipher.unseal(envelope, CONTEXT) == SECRETS


def test_no_plaintext_survives_anywhere_in_the_envelope(
    cipher: EnvelopeCipher,
) -> None:
    envelope = cipher.seal(SECRETS, CONTEXT)

    blob = envelope.wrapped_dek + envelope.dek_nonce + b"".join(
        value.ciphertext + value.nonce for value in envelope.values.values()
    )
    for secret in SECRETS.values():
        assert secret.encode() not in blob


def test_sealing_the_same_secret_twice_produces_different_ciphertext(
    cipher: EnvelopeCipher,
) -> None:
    """A fresh data key and nonce per seal: identical secrets must not be
    recognisable as identical from the stored rows."""
    first = cipher.seal(SECRETS, CONTEXT)
    second = cipher.seal(SECRETS, CONTEXT)

    assert first.values["api_key"].ciphertext != second.values["api_key"].ciphertext
    assert first.wrapped_dek != second.wrapped_dek


def test_opening_under_the_wrong_context_fails(cipher: EnvelopeCipher) -> None:
    """The context is the row identity. A whole envelope copied into another
    row must not decrypt there."""
    envelope = cipher.seal(SECRETS, CONTEXT)

    with pytest.raises(DecryptionFailed, match="unwrap the data key"):
        cipher.unseal(envelope, OTHER_CONTEXT)


def test_a_value_moved_between_fields_fails(cipher: EnvelopeCipher) -> None:
    """Each value is bound to its own name, so the secret cannot be shifted
    into the key's column and read back out."""
    envelope = cipher.seal(SECRETS, CONTEXT)
    swapped = type(envelope)(
        wrapped_dek=envelope.wrapped_dek,
        dek_nonce=envelope.dek_nonce,
        values={
            "api_key": envelope.values["api_secret"],
            "api_secret": envelope.values["api_key"],
        },
    )

    with pytest.raises(DecryptionFailed, match="altered or moved"):
        cipher.unseal(swapped, CONTEXT)


def test_a_tampered_ciphertext_fails(cipher: EnvelopeCipher) -> None:
    envelope = cipher.seal(SECRETS, CONTEXT)
    original = envelope.values["api_key"]
    corrupted = bytearray(original.ciphertext)
    corrupted[0] ^= 0xFF

    tampered = type(envelope)(
        wrapped_dek=envelope.wrapped_dek,
        dek_nonce=envelope.dek_nonce,
        values={
            "api_key": SealedValue(bytes(corrupted), original.nonce),
            "api_secret": envelope.values["api_secret"],
        },
    )

    with pytest.raises(DecryptionFailed):
        cipher.unseal(tampered, CONTEXT)


def test_a_different_master_key_cannot_open_the_envelope(
    cipher: EnvelopeCipher,
) -> None:
    envelope = cipher.seal(SECRETS, CONTEXT)
    stranger = EnvelopeCipher(os.urandom(MASTER_KEY_BYTES))

    with pytest.raises(DecryptionFailed):
        stranger.unseal(envelope, CONTEXT)


def test_a_master_key_of_the_wrong_length_is_rejected() -> None:
    with pytest.raises(InvariantViolation, match="32 bytes"):
        EnvelopeCipher(os.urandom(16))


def test_from_base64_accepts_a_correctly_encoded_key() -> None:
    encoded = base64.b64encode(os.urandom(MASTER_KEY_BYTES)).decode()

    assert isinstance(EnvelopeCipher.from_base64(encoded), EnvelopeCipher)


def test_from_base64_rejects_an_empty_key() -> None:
    with pytest.raises(InvariantViolation, match="not set"):
        EnvelopeCipher.from_base64("")


def test_from_base64_rejects_a_non_base64_key() -> None:
    with pytest.raises(InvariantViolation, match="base64"):
        EnvelopeCipher.from_base64("this is not base64!!!")


def test_sealing_nothing_is_rejected(cipher: EnvelopeCipher) -> None:
    with pytest.raises(InvariantViolation, match="at least one value"):
        cipher.seal({}, CONTEXT)
