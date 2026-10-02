"""CSV processing helpers for ZIP validation and lookups.

This module focuses on reading, validating, and processing the input CSV and
writing the output CSV. Email sending, file movements, and scheduler logic live
in separate steps and are intentionally not included here.
"""

import csv
import logging
import os
import re
import time
from typing import Any, Iterable

import requests
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

logger = logging.getLogger(__name__)


class CSVValidationError(ValueError):
    """Raised when an input CSV is empty, malformed, or missing required headers."""


def read_input_csv(csv_file):
    """Read and validate a CSV file containing zip_code and email columns.

    Args:
        csv_file: Path to the input CSV file.

    Returns:
        A list of dictionaries with cleaned zip_code and email values.

    Raises:
        CSVValidationError: If the file is empty, has missing required headers, or
            contains headers but no data rows.
    """
    try:
        with open(csv_file, "r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames

            if not fieldnames:
                raise CSVValidationError("The input CSV is empty or missing a header row.")

            cleaned_fields = [
                (name or "").strip().lstrip("\ufeff") for name in fieldnames
            ]
            reader.fieldnames = cleaned_fields

            if "zip_code" not in cleaned_fields or "email" not in cleaned_fields:
                raise CSVValidationError(
                    "The input CSV must contain 'zip_code' and 'email' headers."
                )

            rows = []
            for row in reader:
                if row is None:
                    continue
                cleaned_row = {
                    "zip_code": (row.get("zip_code") or "").strip(),
                    "email": (row.get("email") or "").strip(),
                }
                if not any(value not in (None, "") for value in cleaned_row.values()):
                    continue
                rows.append(cleaned_row)

            if not rows:
                raise CSVValidationError(
                    "The input CSV contains headers but no data rows."
                )

            return rows
    except FileNotFoundError as exc:
        raise CSVValidationError(f"Input file not found: {csv_file}") from exc


def _normalize_zip_code(zip_code):
    """Return a normalized ZIP value plus validity details for a row."""
    value = (zip_code or "").strip()
    if value == "":
        return {"cleaned": "", "valid": False, "original": value}
    if " " in value:
        return {"cleaned": value, "valid": False, "original": value}

    if re.fullmatch(r"\d{5}-\d{4}", value):
        return {"cleaned": value[:5], "valid": True, "original": value}

    if value.isdigit():
        if len(value) in {1, 2, 3, 4}:
            logger.warning("ZIP code %s was padded to a five-digit ZIP.", value)
            return {"cleaned": value.zfill(5), "valid": True, "original": value}
        if len(value) == 5:
            return {"cleaned": value, "valid": True, "original": value}

    return {"cleaned": value, "valid": False, "original": value}


def _is_valid_email(email):
    """Validate an email address using Django's email validator."""
    if email is None:
        return False
    email = str(email).strip()
    if not email:
        return False
    try:
        validate_email(email)
        return True
    except ValidationError:
        return False


def _zip_lookup_error(status):
    """Return the base data payload for a ZIP lookup failure."""
    return {"zip_code": "", "state": "", "state_abbreviation": "", "status": status}


def lookup_zip_code(zip_code):
    """Look up a ZIP code through the Zippopotam.us API with retries.

    The function retries temporary failures (timeouts, connection errors, 429,
    and 5xx responses) up to three attempts with a one-second pause before the
    second attempt and a two-second pause before the third.

    Args:
        zip_code: A five-digit ZIP code string.

    Returns:
        A dictionary containing the ZIP, state, abbreviation, and result status.
    """
    normalized = str(zip_code or "").strip()
    url = f"https://api.zippopotam.us/us/{normalized}"
    delays = (1, 2)

    for attempt in range(1, 4):
        try:
            response = requests.get(url, timeout=10)

            if response.status_code == 404:
                logger.warning("ZIP code %s not found.", normalized)
                return {
                    "zip_code": normalized,
                    "state": "",
                    "state_abbreviation": "",
                    "status": "NOT_FOUND",
                }

            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 3:
                    logger.warning(
                        "Temporary ZIP lookup failure for %s on attempt %s; retrying.",
                        normalized,
                        attempt,
                    )
                    time.sleep(delays[attempt - 1])
                    continue
                logger.error("ZIP lookup failed for %s after retries.", normalized)
                return _zip_lookup_error("API_ERROR")

            if 400 <= response.status_code < 500:
                logger.warning(
                    "ZIP lookup returned HTTP %s for %s.",
                    response.status_code,
                    normalized,
                )
                return _zip_lookup_error("API_ERROR")

            payload = response.json()
            places = payload.get("places") or []
            if not places:
                logger.error("ZIP lookup response missing state data for %s.", normalized)
                return _zip_lookup_error("API_ERROR")

            first_place = places[0]
            state = first_place.get("state")
            abbreviation = first_place.get("state abbreviation")
            if not state or not abbreviation:
                logger.error(
                    "ZIP lookup response missing required state information for %s.",
                    normalized,
                )
                return _zip_lookup_error("API_ERROR")

            return {
                "zip_code": normalized,
                "state": state,
                "state_abbreviation": abbreviation,
                "status": "OK",
            }

        except requests.exceptions.TooManyRedirects:
            logger.error("Too many redirects while looking up ZIP %s.", normalized)
            return _zip_lookup_error("API_ERROR")
        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            TimeoutError,
            ConnectionError,
        ):
            if attempt < 3:
                logger.warning(
                    "Temporary ZIP lookup issue for %s on attempt %s; retrying.",
                    normalized,
                    attempt,
                )
                time.sleep(delays[attempt - 1])
                continue
            logger.error("ZIP lookup failed for %s after retries.", normalized)
            return _zip_lookup_error("API_ERROR")
        except requests.exceptions.RequestException:
            logger.error("Request error while looking up ZIP %s.", normalized)
            return _zip_lookup_error("API_ERROR")
        except ValueError:
            logger.error("Invalid JSON returned for ZIP lookup %s.", normalized)
            return _zip_lookup_error("API_ERROR")

    return _zip_lookup_error("API_ERROR")


def process_csv_rows(rows):
    """Apply ZIP lookup and status rules to each CSV row.

    ZIP lookup results are cached per file so each unique ZIP is looked up once,
    while the email validity is checked separately for every row. ZIP problems
    take priority over any email issue.

    Args:
        rows: An iterable of dictionaries containing `zip_code` and `email` keys.

    Returns:
        A list of result dictionaries with zip_code, email, state,
        state_abbreviation, and status keys.
    """
    cache = {}
    results = []

    for row in rows:
        original_zip = str((row or {}).get("zip_code") or "").strip()
        email = str((row or {}).get("email") or "").strip()

        normalized = _normalize_zip_code(original_zip)
        zip_code = normalized["cleaned"]
        zip_valid = normalized["valid"]
        email_valid = _is_valid_email(email)

        if zip_valid:
            if zip_code not in cache:
                cache[zip_code] = lookup_zip_code(zip_code)
            lookup_result = cache[zip_code]
        else:
            lookup_result = {"zip_code": original_zip, "state": "", "state_abbreviation": "", "status": "INVALID_ZIP"}

        if not zip_valid:
            status = "INVALID_ZIP"
            state = ""
            state_abbreviation = ""
        elif lookup_result.get("status") in {"NOT_FOUND", "API_ERROR"}:
            status = lookup_result["status"]
            state = ""
            state_abbreviation = ""
        elif email_valid:
            status = "OK"
            state = lookup_result.get("state", "")
            state_abbreviation = lookup_result.get("state_abbreviation", "")
        else:
            status = "INVALID_EMAIL"
            state = lookup_result.get("state", "")
            state_abbreviation = lookup_result.get("state_abbreviation", "")

        results.append(
            {
                "zip_code": zip_code if zip_valid else original_zip,
                "email": email,
                "state": state,
                "state_abbreviation": state_abbreviation,
                "status": status,
            }
        )

    return results


def write_results_csv(output_path, rows):
    """Write result rows to a UTF-8 CSV file.

    A temporary file is used so partial output is removed if the write fails.

    Args:
        output_path: Target path for the output CSV.
        rows: Iterable of result dictionaries ready to be written.

    Raises:
        Any exception raised during the write process after removing the temporary file.
    """
    temp_path = f"{output_path}.tmp"
    fieldnames = ["zip_code", "email", "state", "state_abbreviation", "status"]

    try:
        with open(temp_path, "w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in fieldnames})
        os.replace(temp_path, output_path)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise
