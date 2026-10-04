"""Inbox scan helpers for processing a single batch of CSV files."""

import logging
import os
from datetime import datetime
from pathlib import Path

from django.conf import settings

from processor.notifications import send_result_notifications
from processor.services import (
    CSVValidationError,
    process_csv_rows,
    read_input_csv,
    write_results_csv,
)

logger = logging.getLogger(__name__)


def _unique_destination_path(directory, original_name):
    """Return a unique file path inside a directory without overwriting existing files."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    stem = Path(original_name).stem
    suffix = Path(original_name).suffix
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    candidate = directory / f"{stem}_{timestamp}{suffix}"
    counter = 1

    while candidate.exists():
        candidate = directory / f"{stem}_{timestamp}_{counter}{suffix}"
        counter += 1

    return candidate


def _move_file_to_directory(source_path, destination_dir):
    """Move a source file into a target directory, keeping a unique destination name."""
    source = Path(source_path)
    destination = Path(destination_dir)
    destination.mkdir(parents=True, exist_ok=True)

    candidate = destination / source.name
    counter = 1
    while candidate.exists():
        candidate = destination / f"{source.stem}_{counter}{source.suffix}"
        counter += 1

    try:
        os.replace(str(source), str(candidate))
    except OSError:
        logger.exception("Could not move %s out of the inbox.", source)
        raise

    return candidate


def process_inbox(inbox_dir=None, output_dir=None, processed_dir=None, error_dir=None):
    """Scan the inbox for CSV files, process each file once, and move it to its final folder.

    The function processes one file at a time, writing the result CSV to the output directory,
    sending the email notifications for valid recipients, and then moving the input file to the
    processed folder. Invalid CSVs, write failures, and file/email issues are moved to the error
    folder and logged so that the next file can continue.
    """
    inbox_dir = Path(inbox_dir or settings.INBOX_DIR)
    output_dir = Path(output_dir or settings.OUTPUT_DIR)
    processed_dir = Path(processed_dir or settings.PROCESSED_DIR)
    error_dir = Path(error_dir or settings.ERROR_DIR)

    for directory in (inbox_dir, output_dir, processed_dir, error_dir):
        directory.mkdir(parents=True, exist_ok=True)

    logger.info("Starting inbox scan for %s.", inbox_dir)
    file_results = []

    for file_path in sorted(inbox_dir.iterdir(), key=lambda item: item.name):
        if not file_path.is_file() or file_path.suffix.lower() != ".csv":
            continue

        logger.info("Scanning file %s.", file_path.name)
        output_path = None

        try:
            rows = read_input_csv(str(file_path))
            result_rows = process_csv_rows(rows)
            output_path = _unique_destination_path(output_dir, file_path.name)
            write_results_csv(str(output_path), result_rows)

            failed_addresses = send_result_notifications(result_rows, file_path.name)
            if failed_addresses:
                logger.warning(
                    "Email failures for %s while processing %s; moving the original file to error.",
                    ", ".join(failed_addresses),
                    file_path.name,
                )
                _move_file_to_directory(file_path, error_dir)
                file_results.append(
                    {"file": file_path.name, "result": "error", "reason": "email_failed"}
                )
                continue

            moved_path = _move_file_to_directory(file_path, processed_dir)
            file_results.append(
                {
                    "file": file_path.name,
                    "result": "processed",
                    "output": str(output_path),
                    "processed_path": str(moved_path),
                }
            )
            logger.info("File %s processed successfully and moved to %s.", file_path.name, moved_path)
        except CSVValidationError as exc:
            logger.error("Invalid input file %s: %s", file_path.name, exc)
            _move_file_to_directory(file_path, error_dir)
            file_results.append({"file": file_path.name, "result": "error", "reason": str(exc)})
        except Exception as exc:
            logger.exception("Unexpected error while processing file %s.", file_path.name)
            _move_file_to_directory(file_path, error_dir)
            file_results.append({"file": file_path.name, "result": "error", "reason": str(exc)})

    logger.info("Inbox scan complete. %s file(s) evaluated.", len(file_results))
    for item in file_results:
        logger.info("File %s result: %s.", item["file"], item["result"])

    return file_results
