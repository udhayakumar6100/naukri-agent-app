"""
otp_reader.py — Automatically reads Naukri OTP from Gmail
Uses Gmail's IMAP to fetch the latest OTP email from Naukri.
"""

import imaplib
import email
import re
import time
import logging

logger = logging.getLogger(__name__)


def fetch_naukri_otp(gmail_address: str, gmail_app_password: str,
                     max_wait_seconds: int = 60) -> str:
    """
    Waits for Naukri OTP email to arrive in Gmail and returns the OTP code.

    Args:
        gmail_address     : your Gmail address
        gmail_app_password: your Gmail App Password (16 chars)
        max_wait_seconds  : how long to wait for email (default 60s)

    Returns:
        OTP string (e.g. "482931") or "" if not found
    """
    logger.info("📧 Waiting for Naukri OTP email in Gmail...")

    wait_interval = 5   # check every 5 seconds
    elapsed       = 0

    while elapsed < max_wait_seconds:
        try:
            otp = _check_gmail_for_otp(gmail_address, gmail_app_password)
            if otp:
                logger.info(f"✅ OTP found: {otp}")
                return otp
        except Exception as e:
            logger.warning(f"   Gmail check error: {e}")

        time.sleep(wait_interval)
        elapsed += wait_interval
        logger.info(f"   Waiting for OTP... ({elapsed}s / {max_wait_seconds}s)")

    logger.error("❌ OTP not received within timeout.")
    return ""


def _check_gmail_for_otp(gmail_address: str, app_password: str) -> str:
    """Connect to Gmail via IMAP and look for Naukri OTP in recent emails."""

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(gmail_address, app_password)
    mail.select("inbox")

    # Search for recent emails from Naukri
    _, msg_ids = mail.search(None, '(FROM "naukri" UNSEEN SUBJECT "OTP")')

    if not msg_ids or not msg_ids[0]:
        # Broader search if specific one fails
        _, msg_ids = mail.search(None, '(FROM "naukri" UNSEEN)')

    mail.logout()

    if not msg_ids or not msg_ids[0]:
        return ""

    # Get the latest email
    latest_id = msg_ids[0].split()[-1]

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(gmail_address, app_password)
    mail.select("inbox")

    _, msg_data = mail.fetch(latest_id, "(RFC822)")
    mail.logout()

    if not msg_data or not msg_data[0]:
        return ""

    raw_email = msg_data[0][1]
    msg       = email.message_from_bytes(raw_email)

    # Extract text from email body
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body += part.get_payload(decode=True).decode("utf-8", errors="ignore")
    else:
        body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

    # Extract 6-digit OTP from body
    otp_match = re.search(r'\b(\d{6})\b', body)
    if otp_match:
        return otp_match.group(1)

    return ""
