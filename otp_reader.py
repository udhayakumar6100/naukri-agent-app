"""
otp_reader.py — Reads fresh Naukri OTP from Gmail
Searches by TODAY's date to avoid thread grouping issues.
"""

import imaplib
import email
import email.utils
import re
import time
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


def fetch_naukri_otp(gmail_address: str, gmail_app_password: str,
                     max_wait_seconds: int = 90) -> str:
    """
    Polls Gmail every 5 seconds for up to 90 seconds.
    Searches by date to bypass Gmail thread grouping.
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
    Search Gmail using SINCE date filter — bypasses thread grouping.
    Returns only OTPs from emails received in the last 5 minutes.
    """
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(gmail_address, app_password)
    mail.select("inbox")

    # Use SINCE to get today's emails only — avoids thread grouping
    today = datetime.now(timezone.utc).strftime("%d-%b-%Y")

    search_queries = [
        f'(FROM "naukri" SINCE "{today}")',
        f'(SUBJECT "OTP" SINCE "{today}")',
        f'(FROM "naukri.com" SINCE "{today}")',
        f'(FROM "naukri")',   # broad fallback without date
    ]

    all_ids = []
    for query in search_queries:
        try:
            _, result = mail.search(None, query)
            if result and result[0]:
                ids = result[0].split()
                if ids:
                    all_ids = ids
                    logger.info(f"   Found {len(ids)} emails: {query}")
                    break
        except Exception as e:
            logger.warning(f"   Search error: {e}")
            continue

    mail.logout()

    if not all_ids:
        logger.warning("   No Naukri emails found")
        return ""

    # Check last 10 emails — newest first — to find freshest OTP
    now_utc    = datetime.now(timezone.utc)
    recent_ids = all_ids[-10:]

    best_otp   = ""
    best_age   = 999

    for msg_id in reversed(recent_ids):
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(gmail_address, app_password)
            mail.select("inbox")
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            mail.logout()

            if not msg_data or not msg_data[0]:
                continue

            msg     = email.message_from_bytes(msg_data[0][1])
            subject = msg.get("Subject", "")
            date_str= msg.get("Date", "")
            age_min = _get_age_minutes(date_str, now_utc)

            logger.info(f"   📨 '{subject}' — age: {age_min:.1f} min")

            # Skip emails older than 8 minutes
            if age_min > 8:
                logger.info(f"   ⏭️  Too old ({age_min:.1f} min) — skipping")
                continue

            body = _get_body(msg)
            if not body:
                continue

            otp = _extract_otp(body)
            if otp and age_min < best_age:
                best_otp = otp
                best_age = age_min
                logger.info(f"   🎯 OTP candidate: {otp} (age: {age_min:.1f} min)")

        except Exception as e:
            logger.warning(f"   Error: {e}")
            continue

    if best_otp:
        logger.info(f"   ✅ Using freshest OTP: {best_otp} (age: {best_age:.1f} min)")

    return best_otp


def _extract_otp(body: str) -> str:
    """Extract OTP number from email body text."""
    patterns = [
        r'OTP[:\s\-]+(\d{4,8})',
        r'code[:\s\-]+(\d{4,8})',
        r'(?<!\d)(\d{6})(?!\d)',
        r'(?<!\d)(\d{4})(?!\d)',
    ]
    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def _get_age_minutes(date_str: str, now_utc: datetime) -> float:
    """Returns how many minutes ago the email was sent."""
    try:
        parsed = email.utils.parsedate_to_datetime(date_str)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (now_utc - parsed).total_seconds() / 60
    except Exception:
        return 999


def _get_body(msg) -> str:
    """Extract full text body from email."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() in ("text/plain", "text/html"):
                try:
                    body += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                except Exception:
                    body += str(part.get_payload())
    else:
        try:
            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
        except Exception:
            body = str(msg.get_payload())
    return body
