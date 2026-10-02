import csv
import os
import tempfile
from unittest import mock

from django.test import SimpleTestCase

from processor.services import (
    CSVValidationError,
    lookup_zip_code,
    process_csv_rows,
    read_input_csv,
    write_results_csv,
)


class ProcessorServiceTests(SimpleTestCase):
    def test_read_input_csv_raises_for_empty_file(self):
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        handle.close()
        try:
            with self.assertRaises(CSVValidationError):
                read_input_csv(handle.name)
        finally:
            os.unlink(handle.name)

    def test_read_input_csv_raises_for_missing_headers(self):
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, newline="")
        handle.write("email\nuser@example.com\n")
        handle.close()
        try:
            with self.assertRaises(CSVValidationError):
                read_input_csv(handle.name)
        finally:
            os.unlink(handle.name)

    def test_read_input_csv_raises_for_headers_without_rows(self):
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, newline="")
        handle.write("zip_code,email\n")
        handle.close()
        try:
            with self.assertRaises(CSVValidationError):
                read_input_csv(handle.name)
        finally:
            os.unlink(handle.name)

    def test_read_input_csv_accepts_bom_and_strips_headers(self):
        temp_path = os.path.join(tempfile.gettempdir(), "processor_bom_test.csv")
        with open(temp_path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([" zip_code ", " email "])
            writer.writerow(["12345", " user@example.com "])

        try:
            rows = read_input_csv(temp_path)
            self.assertEqual(rows, [{"zip_code": "12345", "email": "user@example.com"}])
        finally:
            os.unlink(temp_path)

    @mock.patch("processor.services.lookup_zip_code")
    def test_process_csv_rows_reuses_zip_lookup_cache(self, mock_lookup):
        mock_lookup.return_value = {
            "zip_code": "12345",
            "state": "California",
            "state_abbreviation": "CA",
            "status": "OK",
        }
        rows = [
            {"zip_code": "12345", "email": "user@example.com"},
            {"zip_code": "12345", "email": "other@example.com"},
        ]

        results = process_csv_rows(rows)

        self.assertEqual(mock_lookup.call_count, 1)
        self.assertEqual(results[0]["status"], "OK")
        self.assertEqual(results[1]["status"], "OK")

    @mock.patch("processor.services.lookup_zip_code")
    def test_process_csv_rows_prioritizes_zip_errors_over_email_errors(self, mock_lookup):
        mock_lookup.return_value = {
            "zip_code": "12345",
            "state": "California",
            "state_abbreviation": "CA",
            "status": "OK",
        }
        rows = [
            {"zip_code": "12 345", "email": "bad-email"},
            {"zip_code": "12345", "email": "bad-email"},
        ]

        results = process_csv_rows(rows)

        self.assertEqual(results[0]["status"], "INVALID_ZIP")
        self.assertEqual(results[1]["status"], "INVALID_EMAIL")

    @mock.patch("processor.services.lookup_zip_code")
    def test_process_csv_rows_keeps_state_when_email_is_invalid(self, mock_lookup):
        mock_lookup.return_value = {
            "zip_code": "12345",
            "state": "Texas",
            "state_abbreviation": "TX",
            "status": "OK",
        }
        rows = [{"zip_code": "12345", "email": "not-an-email"}]

        results = process_csv_rows(rows)

        self.assertEqual(results[0]["state"], "Texas")
        self.assertEqual(results[0]["state_abbreviation"], "TX")
        self.assertEqual(results[0]["status"], "INVALID_EMAIL")

    @mock.patch("processor.services.time.sleep")
    @mock.patch("processor.services.requests.get")
    def test_lookup_zip_code_retries_timeouts_and_pauses(self, mock_get, mock_sleep):
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "places": [{"state": "Wisconsin", "state abbreviation": "WI"}]
        }

        mock_get.side_effect = [
            TimeoutError("timed out"),
            mock_response,
        ]

        result = lookup_zip_code("12345")

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["state"], "Wisconsin")
        self.assertEqual(result["state_abbreviation"], "WI")
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once_with(1)

    @mock.patch("processor.services.csv.DictWriter")
    def test_write_results_csv_removes_partial_file_when_write_fails(self, mock_writer):
        temp_path = os.path.join(tempfile.gettempdir(), "processor_output_fail.csv")
        mock_writer.side_effect = OSError("disk full")

        try:
            with self.assertRaises(OSError):
                write_results_csv(
                    temp_path,
                    [{
                        "zip_code": "12345",
                        "email": "user@example.com",
                        "state": "California",
                        "state_abbreviation": "CA",
                        "status": "OK",
                    }],
                )
            self.assertFalse(os.path.exists(temp_path))
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
