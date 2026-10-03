"""Notification helpers for sending per-file ZIP result summaries.

This module groups results by email address, sends a single summary email per
recipient, and returns any addresses whose delivery failed. The inbox job can use
that list later for logging and error handling.
"""

import logging
from collections import OrderedDict

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email

logger = logging.getLogger(__name__)

def _normalize_email_address(email):
    """Return a lowercase email string with surrounding whitespace removed."""
    return (email or "").strip().lower()


def _build_email_body(input_file_name, rows):
    """Build the plain-text summary for one address using that file's rows."""
    lines = [
        f"ZIP code results for {input_file_name}",
        "",
    ]

    for row in rows:
        zip_code = str(row.get("zip_code", ""))
        state = str(row.get("state", ""))
        state_abbreviation = str(row.get("state_abbreviation", ""))
        status = str(row.get("status", ""))
        lines.append(
            f"- {zip_code} | {state or '-'} | {state_abbreviation or '-'} | {status}"
        )

    return "\n".join(lines)


def send_result_notifications(results, input_file_name):
    """Send one summary email per valid address in a result set.

    The function groups rows by normalized email address, preserving the first
    address written for each user and skipping invalid email addresses. It sends
    one file-level message per valid recipient and returns the list of addresses
    whose delivery failed.

    Args:
        results: A list of row dictionaries returned by ``process_csv_rows``.
        input_file_name: The original input CSV filename used in the subject.

    Returns:
        A list of email addresses that failed to send.
    """
    grouped_results = OrderedDict()

    # Keep the first-seen casing for each email while deduplicating duplicates.
    for row in results or []:
        email = (row.get("email") or "").strip()
        if not email:
            continue

        try:
            validate_email(email)
        except ValidationError:
            logger.info("Skipping invalid email address %s for file %s.", email, input_file_name)
            continue

        normalized_email = _normalize_email_address(email)
        if normalized_email not in grouped_results:
            grouped_results[normalized_email] = {
                "email": email,
                "rows": [],
            }
        grouped_results[normalized_email]["rows"].append(row)

    failed_addresses = []
    sender = getattr(settings, "DEFAULT_FROM_EMAIL", "zip-notifier@example.com")

    for recipient_group in grouped_results.values():
        recipient_email = recipient_group["email"]
        message = _build_email_body(input_file_name, recipient_group["rows"])
        subject = f"ZIP code results for {input_file_name}"

        try:
            send_mail(
                subject,
                message,
                sender,
                [recipient_email],
                fail_silently=False,
            )
            logger.info("Email sent to %s for file %s.", recipient_email, input_file_name)
        except Exception:
            logger.exception(
                "Email failed for %s while processing file %s.",
                recipient_email,
                input_file_name,
            )
            failed_addresses.append(recipient_email)

    return failed_addresses
