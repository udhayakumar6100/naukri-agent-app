"""
otp_reader.py — Automatically reads Naukri OTP from Gmail
Uses Gmail IMAP — searches broadly (read + unread) for reliability.
"""

import imaplib
import email
import re
import time
import logging

logger = logging.getLogger(__name__)


def fetch_naukri_otp(gmail_address: str, gmail_app_password: str,
                     max_wait_seconds: int = 90) -> str:
    """
    Polls Gmail every 5 seconds for up to 90 seconds waiting for Naukri OTP.
    Returns the OTP string or "" if not found.
    """
    logger.info("📧 Waiting for Naukri OTP email in Gmail...")

    elapsed = 0
    while elapsed < max_wait_seconds:
        try:
            otp = _check_gmail_for_otp(gmail_address, gmail_app_password)
            if otp:
                logger.info(f"✅ OTP found: {otp}")
                return otp
        except Exception as e:
            logger.warning(f"   Gmail check error: {e}")

        time.sleep(5)
        elapsed += 5
        logger.info(f"   Waiting for OTP... ({elapsed}s / {max_wait_seconds}s)")

    logger.error("❌ OTP not received within timeout.")
    return ""


def _check_gmail_for_otp(gmail_address: str, app_password: str) -> str:
    """
    Connects to Gmail and searches recent Naukri emails for an OTP.
    Searches read AND unread emails — no longer restricted to UNSEEN only.
    """
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(gmail_address, app_password)
    mail.select("inbox")

    # Try multiple search strategies — broader first
    search_queries = [
        '(FROM "naukri")',
        '(FROM "naukri.com")',
        '(SUBJECT "OTP")',
        '(SUBJECT "login")',
        '(FROM "no-reply@naukri.com")',
        '(FROM "donotreply@naukri.com")',
    ]

    msg_ids_found = []
    for query in search_queries:
        try:
            _, result = mail.search(None, query)
            if result and result[0]:
                ids = result[0].split()
                if ids:
                    msg_ids_found = ids
                    logger.info(f"   Found {len(ids)} emails matching: {query}")
                    break
        except Exception as e:
            logger.warning(f"   Search error for '{query}': {e}")
            continue

    mail.logout()

    if not msg_ids_found:
        logger.warning("   No Naukri emails found in inbox")
        return ""

    # Check the 5 most recent matching emails
    recent_ids = msg_ids_found[-5:]

    for msg_id in reversed(recent_ids):
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(gmail_address, app_password)
            mail.select("inbox")
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            mail.logout()

            if not msg_data or not msg_data[0]:
                continue

            msg = email.message_from_bytes(msg_data[0][1])
            subject = msg.get("Subject", "")
            logger.info(f"   Checking: '{subject}'")

            body = _get_email_body(msg)
            if not body:
                continue

            # Try OTP patterns from most specific to least
            patterns = [
                r'OTP[:\s\-]+(\d{4,8})',
                r'code[:\s\-]+(\d{4,8})',
                r'(?<!\d)(\d{6})(?!\d)',
                r'(?<!\d)(\d{4})(?!\d)',
            ]

            for pattern in patterns:
                match = re.search(pattern, body, re.IGNORECASE)
                if match:
                    otp = match.group(1)
                    logger.info(f"   ✅ OTP extracted: {otp}")
                    return otp

        except Exception as e:
            logger.warning(f"   Error reading email: {e}")
            continue

    return ""


def _get_email_body(msg) -> str:
    """Extract plain text or HTML body from email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type in ("text/plain", "text/html"):
                try:
                    body += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                except Exception:
                    try:
                        body += str(part.get_payload())
                    except Exception:
                        pass
    else:
        try:
            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
        except Exception:
            body = str(msg.get_payload())
    return body
