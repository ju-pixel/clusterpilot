"""Best-effort operator push when an upstream generation failure is our fault.

Issue #61: when the master Anthropic key is revoked (401) or the account runs
out of credit (a 400 naming the credit balance), every hosted generation fails
at once and the only signal was a subscriber saying the tool was broken. One
line to an ntfy topic means the operator hears about it before they do.

Three deliberate limits, because an alert must never make an outage worse:

  * It never raises. A dead ntfy endpoint is logged and dropped.
  * It never delays a response. ``maybe_alert`` schedules the POST as a
    background task and returns, and the POST itself has a short timeout.
  * It is rate limited in memory, one push per status code per ten minutes,
    so 150 identical failures are one push rather than 150.

The rate-limit state is per process, so a restart or a second Fly machine can
each send one push. That is the right trade for state nobody has to maintain,
and duplicates of a real outage are harmless.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# One push per status code per ten minutes.
_ALERT_INTERVAL_SECONDS = 600.0

# Short: this runs whilst a user is already waiting on a failed generation.
_ALERT_TIMEOUT_SECONDS = 5.0

# Enough of the upstream body to tell the two failures apart at a glance.
_BODY_CHARS = 120

# Monotonic timestamp of the last push per status code.
_last_sent: dict[int, float] = {}

# Strong references to in-flight pushes: asyncio only holds weak ones, so a
# task nobody keeps can be garbage collected before it runs.
_background: set[asyncio.Task] = set()


def is_alertable(status_code: int, body: str) -> bool:
    """True for the upstream failures that break the hosted tier for everyone.

    A 401 is a revoked, rotated or mistyped master key; a 400 naming the credit
    balance is an empty Anthropic account. Both need a human. Everything else
    (429, 5xx, a malformed payload) is transient or belongs to one request, and
    paging on those would train the operator to ignore the topic.
    """
    if status_code == 401:
        return True
    return status_code == 400 and "credit balance" in body.lower()


def claim_alert(
    route: str,
    status_code: int,
    body: str,
    *,
    now: float | None = None,
) -> str | None:
    """The line to push for this failure, or None when no push is due.

    Claims the rate-limit slot as a side effect, so two concurrent failures
    cannot both decide they are the one that gets to send.
    """
    if not settings.ops_ntfy_url:
        return None
    if not is_alertable(status_code, body):
        return None

    moment = time.monotonic() if now is None else now
    last = _last_sent.get(status_code)
    if last is not None and moment - last < _ALERT_INTERVAL_SECONDS:
        return None
    _last_sent[status_code] = moment

    return f"ClusterPilot proxy: {route} got {status_code} from Anthropic: {body[:_BODY_CHARS]}"


async def _post(message: str) -> None:
    """POST one plain-text line to the configured endpoint, swallowing failures."""
    try:
        async with httpx.AsyncClient(timeout=_ALERT_TIMEOUT_SECONDS) as client:
            await client.post(settings.ops_ntfy_url, content=message.encode("utf-8"))
    except Exception:
        # Anything at all: the alert is a courtesy, and it must not turn one
        # upstream failure into a second, unhandled one.
        logger.warning("Operator alert POST failed", exc_info=True)


def maybe_alert(route: str, status_code: int, body: str) -> None:
    """Schedule one operator push for an upstream failure, if it warrants one.

    Returns immediately. Callers are on the request path, and a slow or dead
    ntfy endpoint must not add its timeout to a generation that has already
    failed.
    """
    message = claim_alert(route, status_code, body)
    if message is None:
        return

    try:
        task = asyncio.get_running_loop().create_task(_post(message))
    except RuntimeError:
        # No running loop, so nothing to schedule onto. Only reachable from a
        # synchronous caller; the routes are all async.
        logger.warning("Operator alert not sent, no running event loop")
        return

    _background.add(task)
    task.add_done_callback(_background.discard)
