"""Managed API key lifecycle.

ClusterPilot issues its own opaque bearer tokens (Option B proxy pattern).
The daemon authenticates to the CP API with this token; the API then calls
Anthropic using its own master key. No Workspaces API required.

Key format: cp-<40 hex chars>  (e.g. cp-a3f8c2...)
Storage: bcrypt hash + 4-char display prefix (e.g. "a3f8")
"""

import secrets

import bcrypt


_PREFIX = "cp-"
_TOKEN_BYTES = 20  # 40 hex chars


def generate_key() -> str:
    """Generate a new plaintext key. Shown to the user exactly once."""
    return _PREFIX + secrets.token_hex(_TOKEN_BYTES)


def hash_key(key: str) -> str:
    """Return a bcrypt hash of the key for storage."""
    return bcrypt.hashpw(key.encode(), bcrypt.gensalt()).decode()


def verify_key(key: str, hashed: str) -> bool:
    """Return True if the plaintext key matches the stored hash."""
    return bcrypt.checkpw(key.encode(), hashed.encode())


def key_prefix(key: str) -> str:
    """Return the first 4 chars after the 'cp-' prefix for masked display."""
    return key[len(_PREFIX):len(_PREFIX) + 4]
