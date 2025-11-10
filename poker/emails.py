import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)


def send_org_access_token(email: str, token: str) -> bool:
    """
    Send a 6-digit access token via the configured email backend.
    Returns True on success, False otherwise.
    """
    sender = settings.DEFAULT_FROM_EMAIL
    ttl_minutes = max(settings.ORG_ACCESS_TOKEN_TTL_SECONDS // 60, 1)
    subject = "Your Planning Poker access code"
    body_text = (
        "Here is your Planning Poker verification code:\n\n"
        f"    {token}\n\n"
        f"It expires in {ttl_minutes} minute(s). If you did not request this code you can ignore this email."
    )
    body_html = f"""
        <p>Here is your Planning Poker verification code:</p>
        <p style="font-size:18px;font-weight:bold;">{token}</p>
        <p>This code expires in {ttl_minutes} minute(s). If you did not request it, you can ignore this email.</p>
    """

    try:
        msg = EmailMultiAlternatives(subject, body_text, sender, [email])
        msg.attach_alternative(body_html, "text/html")
        msg.send(fail_silently=False)
        logger.info("Sent org access token email to %s", email)
        return True
    except Exception as exc:  # pragma: no cover - depends on email backend
        logger.error("Failed to send email to %s: %s", email, exc, exc_info=True)
        return False
