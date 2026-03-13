#!/usr/bin/env python3
"""Manage ClusterPilot beta tokens.

Tokens are stored locally in tokens.txt (gitignored), one "token:name" per
line.  Use the `env` command to generate the fly secrets command to deploy
them.

Usage:
    python manage_tokens.py add "Alice Smith"   # generate a new token
    python manage_tokens.py list               # show all tokens
    python manage_tokens.py revoke <token>     # remove a token
    python manage_tokens.py env                # print the fly secrets command
"""
from __future__ import annotations

import sys
import uuid

_TOKENS_FILE = "tokens.txt"
_PROXY_URL = "https://clusterpilot-proxy.fly.dev"


def _load() -> list[tuple[str, str]]:
    try:
        pairs = []
        with open(_TOKENS_FILE) as f:
            for line in f:
                line = line.strip()
                if line and ":" in line:
                    token, name = line.split(":", 1)
                    pairs.append((token.strip(), name.strip()))
        return pairs
    except FileNotFoundError:
        return []


def _save(pairs: list[tuple[str, str]]) -> None:
    with open(_TOKENS_FILE, "w") as f:
        for token, name in pairs:
            f.write(f"{token}:{name}\n")


def cmd_add(name: str) -> None:
    token = str(uuid.uuid4())
    pairs = _load()
    pairs.append((token, name))
    _save(pairs)
    print(f"Token created for {name!r}:")
    print(f"  {token}")
    print()
    print("Send them this config snippet:")
    print()
    print("  [defaults]")
    print(f'  api_key      = "{token}"')
    print(f'  api_base_url = "{_PROXY_URL}"')
    print()
    print("Then run  python manage_tokens.py env  and redeploy.")


def cmd_list() -> None:
    pairs = _load()
    if not pairs:
        print("No tokens.")
        return
    print(f"{'TOKEN PREFIX':<14}  NAME")
    print("-" * 40)
    for token, name in pairs:
        print(f"  {token[:8]}…    {name}")


def cmd_revoke(token_prefix: str) -> None:
    pairs = _load()
    before = len(pairs)
    pairs = [(t, n) for t, n in pairs if not t.startswith(token_prefix)]
    if len(pairs) == before:
        print(f"No token starting with {token_prefix!r} found.")
        return
    _save(pairs)
    removed = before - len(pairs)
    print(f"Revoked {removed} token(s). Run  python manage_tokens.py env  and redeploy.")


def cmd_env() -> None:
    pairs = _load()
    if not pairs:
        print("No tokens. Add some first.")
        return
    env_val = ",".join(f"{token}:{name}" for token, name in pairs)
    print("Run this to update Fly.io secrets:")
    print()
    print(f'  fly secrets set BETA_TOKENS="{env_val}"')


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "add" and len(sys.argv) >= 3:
        cmd_add(" ".join(sys.argv[2:]))
    elif cmd == "list":
        cmd_list()
    elif cmd == "revoke" and len(sys.argv) >= 3:
        cmd_revoke(sys.argv[2])
    elif cmd == "env":
        cmd_env()
    else:
        print(__doc__)
        sys.exit(1)
