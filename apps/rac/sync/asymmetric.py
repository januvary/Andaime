#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Asymmetric encryption for the collection layer.

Each RAC instance encrypts its snapshot to the admin's X25519 public key.
Only the admin (GitHub Action, holding the private key) can decrypt.

This is the ``age`` design: hybrid encryption using X25519 ECDH + HKDF +
AES-GCM. The public key ships in the RAC installer (it is not a secret).
The private key lives only as a GitHub Secret.

Only depends on ``cryptography`` + stdlib — no andaime, no PySide6, no DB.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_INFO = b"rac-collection-v1"
_KEY_LEN = 32
_NONCE_LEN = 12


def generate_keypair() -> tuple[str, str]:
    """Generate an X25519 keypair. Returns (private_pem, public_pem)."""
    private = X25519PrivateKey.generate()
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    public_pem = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    return private_pem, public_pem


def _load_private_key(pem: str) -> X25519PrivateKey:
    loaded = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    assert isinstance(loaded, X25519PrivateKey)
    return loaded


def _load_public_key(pem: str) -> X25519PublicKey:
    loaded = serialization.load_pem_public_key(pem.encode("ascii"))
    assert isinstance(loaded, X25519PublicKey)
    return loaded


def encrypt_to_public_key(plaintext: bytes, recipient_public_pem: str) -> dict:
    recipient_pub = _load_public_key(recipient_public_pem)

    ephemeral = X25519PrivateKey.generate()
    shared = ephemeral.exchange(recipient_pub)
    ephemeral_pub_bytes = ephemeral.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    wrapping_key = HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_LEN,
        salt=None,
        info=_INFO,
    ).derive(shared)

    file_key = os.urandom(_KEY_LEN)
    payload_nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(file_key).encrypt(payload_nonce, plaintext, None)

    wrap_nonce = os.urandom(_NONCE_LEN)
    wrapped_key = AESGCM(wrapping_key).encrypt(wrap_nonce, file_key, None)

    return {
        "ephemeral_pub": base64.b64encode(ephemeral_pub_bytes).decode("ascii"),
        "wrapped_key": base64.b64encode(wrapped_key).decode("ascii"),
        "wrap_nonce": base64.b64encode(wrap_nonce).decode("ascii"),
        "payload_nonce": base64.b64encode(payload_nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def decrypt_with_private_key(blob: dict, private_pem: str) -> bytes:
    private = _load_private_key(private_pem)

    ephemeral_pub = X25519PublicKey.from_public_bytes(
        base64.b64decode(blob["ephemeral_pub"])
    )
    shared = private.exchange(ephemeral_pub)

    wrapping_key = HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_LEN,
        salt=None,
        info=_INFO,
    ).derive(shared)

    file_key = AESGCM(wrapping_key).decrypt(
        base64.b64decode(blob["wrap_nonce"]),
        base64.b64decode(blob["wrapped_key"]),
        None,
    )
    return AESGCM(file_key).decrypt(
        base64.b64decode(blob["payload_nonce"]),
        base64.b64decode(blob["ciphertext"]),
        None,
    )
