"""Check PyPI for a newer version of ClusterPilot."""
from __future__ import annotations

import logging

import httpx

from clusterpilot import __version__

log = logging.getLogger(__name__)

_PYPI_URL = "https://pypi.org/pypi/clusterpilot/json"


def _parse_version(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


async def check_for_update() -> str | None:
    """Return latest PyPI version string if newer than installed, else None.

    Fails silently on any network or parse error.
    """
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(_PYPI_URL)
            r.raise_for_status()
            latest = r.json()["info"]["version"]
        if _parse_version(latest) > _parse_version(__version__):
            return latest
        return None
    except Exception as exc:
        log.debug("PyPI update check failed: %s", exc)
        return None
