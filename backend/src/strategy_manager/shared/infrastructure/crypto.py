"""Envelope encryption for secrets held at rest (CLAUDE.md rule 8).

Two layers, not one. A randomly generated data key (DEK) encrypts the secret;
the master key (KEK) from ``MASTER_ENCRYPTION_KEY`` encrypts only that data
key. Encrypting the secret with the master key directly would be simpler and
would work — right up to the day the master key has to be rotated, at which
point every stored secret has to be decrypted and re-encrypted. With an
envelope, rotation rewrites a handful of wrapped data keys and never touches
the ciphertexts.

AES-256-GCM throughout, so every ciphertext is authenticated: tampering is
detected on decryption rather than surfacing as a corrupted secret that gets
sent to an exchange.

Each value is bound to its own context string, which is fed to GCM as
additional authenticated data. The ciphertext of one credential's secret
therefore cannot be pasted into another credential's row, or into the key
column of its own row, without decryption failing. Without that binding, the
database's own integrity becomes the only thing stopping a swap.
"""

import base64
import binascii
import os
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from strategy_manager.shared.domain.errors import InvariantViolation

MASTER_KEY_BYTES = 32
NONCE_BYTES = 12


class DecryptionFailed(InvariantViolation):
    """A ciphertext failed authentication.

    Means one of: the wrong master key, a tampered row, or a value moved
    between columns or rows. All three are the same instruction — stop, do
    not use this secret.
    """


@dataclass(frozen=True, slots=True)
class SealedValue:
    """One encrypted value and the nonce it was encrypted under."""

    ciphertext: bytes
    nonce: bytes


@dataclass(frozen=True, slots=True)
class Envelope:
    """A wrapped data key plus every value that data key protects."""

    wrapped_dek: bytes
    dek_nonce: bytes
    values: Mapping[str, SealedValue]


class EnvelopeCipher:
    """Seals and opens envelopes under one master key."""

    def __init__(self, master_key: bytes) -> None:
        if len(master_key) != MASTER_KEY_BYTES:
            raise InvariantViolation(
                f"master encryption key must be {MASTER_KEY_BYTES} bytes, "
                f"got {len(master_key)}"
            )
        self._kek = AESGCM(master_key)

    @classmethod
    def from_base64(cls, encoded: str) -> "EnvelopeCipher":
        """Builds a cipher from the base64 form stored in the environment."""
        if not encoded:
            raise InvariantViolation(
                "MASTER_ENCRYPTION_KEY is not set; credentials cannot be sealed "
                "or opened without it"
            )
        try:
            master_key = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise InvariantViolation(
                "MASTER_ENCRYPTION_KEY is not valid base64"
            ) from exc
        return cls(master_key)

    def seal(self, values: Mapping[str, str], context: str) -> Envelope:
        """Encrypts every value under one fresh data key.

        ``context`` identifies the row these values belong to and is bound
        into every ciphertext, so moving one elsewhere breaks decryption.
        """
        if not values:
            raise InvariantViolation("seal() needs at least one value")

        dek = AESGCM.generate_key(bit_length=256)
        dek_nonce = _nonce()
        wrapped_dek = self._kek.encrypt(dek_nonce, dek, context.encode("utf-8"))

        cipher = AESGCM(dek)
        sealed = {
            name: SealedValue(
                ciphertext=cipher.encrypt(
                    (nonce := _nonce()), value.encode("utf-8"), _aad(context, name)
                ),
                nonce=nonce,
            )
            for name, value in values.items()
        }

        return Envelope(wrapped_dek=wrapped_dek, dek_nonce=dek_nonce, values=sealed)

    def unseal(self, envelope: Envelope, context: str) -> dict[str, str]:
        """Recovers the plaintexts. Raises ``DecryptionFailed`` on any
        authentication failure rather than returning something unusable."""
        try:
            dek = self._kek.decrypt(
                envelope.dek_nonce, envelope.wrapped_dek, context.encode("utf-8")
            )
        except InvalidTag as exc:
            raise DecryptionFailed(
                f"could not unwrap the data key for '{context}': wrong master key, "
                "or the stored row was altered"
            ) from exc

        cipher = AESGCM(dek)
        opened: dict[str, str] = {}
        for name, value in envelope.values.items():
            try:
                plaintext = cipher.decrypt(
                    value.nonce, value.ciphertext, _aad(context, name)
                )
            except InvalidTag as exc:
                raise DecryptionFailed(
                    f"could not decrypt '{name}' for '{context}': the stored value "
                    "was altered or moved from another record"
                ) from exc
            opened[name] = plaintext.decode("utf-8")

        return opened


def _nonce() -> bytes:
    """A fresh random nonce per encryption.

    GCM catastrophically loses confidentiality if a nonce repeats under the
    same key. Every ``seal`` generates a new data key anyway, so a 96-bit
    random nonce has no realistic chance of colliding within one key's use.
    """
    return os.urandom(NONCE_BYTES)


def _aad(context: str, name: str) -> bytes:
    return f"{context}/{name}".encode()
