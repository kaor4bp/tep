"""Weak proof-of-work helpers for ledger append friction."""

from __future__ import annotations

import hashlib
import math
import secrets
import time
from typing import Any

from .errors import PowError
from .jsoncanon import canonical_bytes


def leading_zero_bits(hash_hex: str) -> int:
    if hash_hex.startswith("sha256:"):
        hash_hex = hash_hex.removeprefix("sha256:")
    bits = bin(int(hash_hex, 16))[2:].zfill(len(hash_hex) * 4)
    return len(bits) - len(bits.lstrip("0"))


def meets_difficulty(work_hash: str, difficulty_bits: int) -> bool:
    return leading_zero_bits(work_hash) >= difficulty_bits


def work_hash(base: dict[str, Any], nonce: str) -> str:
    payload = dict(base)
    payload["nonce"] = nonce
    return "sha256:" + hashlib.sha256(canonical_bytes(payload)).hexdigest()


def mine_pow(base: dict[str, Any], difficulty_bits: int, *, max_attempts: int | None = None) -> dict[str, Any]:
    if difficulty_bits < 0:
        raise PowError("difficulty_bits must be non-negative")
    prefix = secrets.token_hex(8)
    attempt = 0
    while max_attempts is None or attempt < max_attempts:
        nonce = f"{prefix}:{attempt}"
        digest = work_hash(base, nonce)
        if meets_difficulty(digest, difficulty_bits):
            return {
                "nonce": nonce,
                "difficulty_bits": difficulty_bits,
                "work_hash": digest,
            }
        attempt += 1
    raise PowError("unable to satisfy proof-of-work within max_attempts")


def verify_pow(base: dict[str, Any], proof: dict[str, Any]) -> bool:
    nonce = proof.get("nonce")
    difficulty_bits = proof.get("difficulty_bits")
    expected = proof.get("work_hash")
    if not isinstance(nonce, str) or not isinstance(difficulty_bits, int) or not isinstance(expected, str):
        return False
    actual = work_hash(base, nonce)
    return actual == expected and meets_difficulty(actual, difficulty_bits)


def estimate_difficulty(target_seconds: float = 1.5, *, sample_hashes: int = 20_000) -> int:
    """Estimate local difficulty for approximately target_seconds work.

    This only benchmarks hashing throughput; it does not mine a target during
    calibration, so callers can run it before choosing a policy.
    """

    if target_seconds <= 0:
        raise ValueError("target_seconds must be positive")
    base = {"calibration": "tep-pow", "sample": 1}
    start = time.perf_counter()
    for index in range(sample_hashes):
        work_hash(base, str(index))
    elapsed = max(time.perf_counter() - start, 1e-9)
    hashes_per_second = sample_hashes / elapsed
    expected_hashes = max(hashes_per_second * target_seconds, 1)
    return max(0, int(math.log2(expected_hashes)))

