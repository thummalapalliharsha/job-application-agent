"""Hashed PIN configuration for authorizing canonical profile writes."""
from __future__ import annotations

import hashlib
import hmac
import getpass
import os
import re
import secrets
import sys

_PIN_PATTERN = re.compile(r"[0-9]{6}\Z")
_HASH_ENV = "CAREER_OS_PROFILE_PIN_HASH"
_SCRYPT_N = 1 << 15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LENGTH = 32
_SCRYPT_MAX_MEMORY = 64 * 1024 * 1024


class ProfilePinVerificationError(PermissionError):
    """Raised when a profile write lacks a valid PIN."""


def _validate_pin(pin: object) -> str:
    if not isinstance(pin, str) or _PIN_PATTERN.fullmatch(pin) is None:
        raise ValueError("The security PIN must contain exactly six digits.")
    return pin


def _derive(pin: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        pin.encode("ascii"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_LENGTH,
        maxmem=_SCRYPT_MAX_MEMORY,
    )


def _parse_hash(encoded: str) -> tuple[bytes, bytes] | None:
    try:
        algorithm, n, r, p, salt_hex, digest_hex = encoded.split("$")
        if (algorithm != "scrypt" or int(n) != _SCRYPT_N
                or int(r) != _SCRYPT_R or int(p) != _SCRYPT_P):
            return None
        salt = bytes.fromhex(salt_hex)
        digest = bytes.fromhex(digest_hex)
        if len(salt) != 16 or len(digest) != _SCRYPT_LENGTH:
            return None
        return salt, digest
    except (TypeError, ValueError):
        return None


def hash_profile_pin(pin: object) -> str:
    pin = _validate_pin(pin)
    salt = secrets.token_bytes(16)
    digest = _derive(pin, salt)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def pin_is_configured() -> bool:
    encoded = os.environ.get(_HASH_ENV, "").strip()
    return _parse_hash(encoded) is not None


def verify_profile_pin(pin: object) -> None:
    if not isinstance(pin, str) or _PIN_PATTERN.fullmatch(pin) is None:
        raise ProfilePinVerificationError("A valid six-digit security PIN is required. No profile changes were saved.")
    encoded = os.environ.get(_HASH_ENV, "").strip()
    parsed = _parse_hash(encoded)
    if parsed is None:
        raise ProfilePinVerificationError("Profile PIN verification is not configured. No profile changes were saved.")
    salt, expected = parsed
    candidate = _derive(pin, salt)
    if not hmac.compare_digest(candidate, expected):
        raise ProfilePinVerificationError("A valid six-digit security PIN is required. No profile changes were saved.")


def main() -> int:
    pin = getpass.getpass("Enter six-digit profile PIN: ")
    confirmation = getpass.getpass("Confirm profile PIN: ")
    if not _PIN_PATTERN.fullmatch(pin) or not hmac.compare_digest(pin, confirmation):
        print("PIN entries must match and contain exactly six digits.", file=sys.stderr)
        return 1
    print(hash_profile_pin(pin))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
