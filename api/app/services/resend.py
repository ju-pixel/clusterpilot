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
