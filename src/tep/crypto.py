"""Agent identity and Ed25519 seal primitives."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .errors import OwnershipError, SealError
from .ids import new_id

SEAL_SUITE = "cryptography-ed25519-v1"
PRIVATE_PREFIX = "ed25519-private:"
PUBLIC_PREFIX = "ed25519-public:"
SEAL_PREFIX = "ed25519:"


@dataclass(frozen=True)
class AgentIdentity:
    agent_ref: str
    agent_name: str
    private_key: str
    public_key: str
    key_fingerprint: str
    seal_suite: str = SEAL_SUITE


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _fingerprint(public_raw: bytes) -> str:
    material = SEAL_SUITE.encode("utf-8") + b"\0" + public_raw
    return "sha256:" + hashlib.sha256(material).hexdigest()


def generate_agent_identity(agent_name: str | None = None) -> AgentIdentity:
    private = Ed25519PrivateKey.generate()
    private_raw = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    fingerprint = _fingerprint(public_raw)
    if agent_name is None:
        agent_name = f"agent-{fingerprint[-12:]}"
    return AgentIdentity(
        agent_ref=new_id("AGENT"),
        agent_name=agent_name,
        private_key=PRIVATE_PREFIX + _b64(private_raw),
        public_key=PUBLIC_PREFIX + _b64(public_raw),
        key_fingerprint=fingerprint,
    )


def public_key_from_private(private_key: str) -> str:
    private = _load_private_key(private_key)
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return PUBLIC_PREFIX + _b64(public_raw)


def fingerprint_for_public_key(public_key: str) -> str:
    return _fingerprint(_public_raw(public_key))


def assert_private_key_matches(public_key: str, key_fingerprint: str, private_key: str) -> None:
    derived_public = public_key_from_private(private_key)
    if derived_public != public_key or fingerprint_for_public_key(derived_public) != key_fingerprint:
        raise OwnershipError("private key does not match current agent public identity")


def sign(private_key: str, payload: bytes) -> str:
    private = _load_private_key(private_key)
    return SEAL_PREFIX + _b64(private.sign(payload))


def verify(public_key: str, payload: bytes, seal: str) -> bool:
    if not seal.startswith(SEAL_PREFIX):
        raise SealError("unsupported seal prefix")
    public = Ed25519PublicKey.from_public_bytes(_public_raw(public_key))
    try:
        public.verify(_unb64(seal.removeprefix(SEAL_PREFIX)), payload)
    except InvalidSignature:
        return False
    return True


def _load_private_key(private_key: str) -> Ed25519PrivateKey:
    if not private_key.startswith(PRIVATE_PREFIX):
        raise OwnershipError("unsupported private key format")
    return Ed25519PrivateKey.from_private_bytes(_unb64(private_key.removeprefix(PRIVATE_PREFIX)))


def _public_raw(public_key: str) -> bytes:
    if not public_key.startswith(PUBLIC_PREFIX):
        raise SealError("unsupported public key format")
    return _unb64(public_key.removeprefix(PUBLIC_PREFIX))

