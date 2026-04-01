"""Resend transactional email wrappers."""

import resend

from app.config import settings

resend.api_key = settings.resend_api_key


async def send_welcome_email(to_email: str) -> None:
    resend.Emails.send({
        "from": settings.resend_from_address,
        "to": [to_email],
        "subject": "Welcome to ClusterPilot",
        "html": (
            "<p>Your ClusterPilot account is ready.</p>"
            "<p>Visit <a href='https://app.clusterpilot.sh'>app.clusterpilot.sh</a> "
            "to connect your first cluster.</p>"
        ),
    })


async def send_subscription_started_email(to_email: str) -> None:
    resend.Emails.send({
        "from": settings.resend_from_address,
        "to": [to_email],
        "subject": "ClusterPilot subscription activated",
        "html": (
            "<p>Your ClusterPilot subscription is now active.</p>"
            "<p>Your managed API key is available in the Account tab of your dashboard.</p>"
        ),
    })


async def send_pi_invite_codes_email(to_email: str, codes: list[str]) -> None:
    code_rows = "".join(
        f"<li style='font-family:monospace;font-size:16px;margin:6px 0;letter-spacing:0.05em'>{c}</li>"
        for c in codes
    )
    resend.Emails.send({
        "from": settings.resend_from_address,
        "to": [to_email],
        "subject": "ClusterPilot — your group invite codes",
        "html": (
            "<p>Your ClusterPilot group subscription is active. "
            "Share each code below with one researcher in your group.</p>"
            "<p>Each code is redeemed once at "
            "<a href='https://app.clusterpilot.sh'>app.clusterpilot.sh</a> "
            "via Account → Redeem invite code.</p>"
            f"<ul>{code_rows}</ul>"
            "<p>If you need to check your codes later, they are listed in "
            "the Account tab of your dashboard.</p>"
        ),
    })


async def send_payment_failed_email(to_email: str) -> None:
    resend.Emails.send({
        "from": settings.resend_from_address,
        "to": [to_email],
        "subject": "ClusterPilot — payment failed",
        "html": (
            "<p>We could not process your last ClusterPilot payment.</p>"
            "<p>Please update your payment method in the "
            "<a href='https://app.clusterpilot.sh'>Account tab</a>.</p>"
        ),
    })
