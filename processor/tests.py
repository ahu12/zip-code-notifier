import csv
import os
import tempfile
from unittest import mock

import requests
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

    def test_read_input_csv_raises_for_missing_file(self):
        missing_path = os.path.join(tempfile.gettempdir(), "missing_processor_input.csv")
        self.assertFalse(os.path.exists(missing_path))
        with self.assertRaises(FileNotFoundError):
            read_input_csv(missing_path)

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

    @mock.patch("processor.services.lookup_zip_code")
    def test_process_csv_rows_applies_zip_rules(self, mock_lookup):
        mock_lookup.side_effect = [
            {"zip_code": "12345", "state": "California", "state_abbreviation": "CA", "status": "OK"},
            {"zip_code": "00042", "state": "Texas", "state_abbreviation": "TX", "status": "OK"},
        ]
        rows = [
            {"zip_code": "12345", "email": "user@example.com"},
            {"zip_code": "12345-6789", "email": "user@example.com"},
            {"zip_code": "42", "email": "user@example.com"},
            {"zip_code": "12 345", "email": "user@example.com"},
            {"zip_code": "ABC", "email": "user@example.com"},
            {"zip_code": "", "email": "user@example.com"},
            {"zip_code": "123-4567", "email": "user@example.com"},
        ]

        results = process_csv_rows(rows)

        self.assertEqual(results[0]["zip_code"], "12345")
        self.assertEqual(results[1]["zip_code"], "12345")
        self.assertEqual(results[2]["zip_code"], "00042")
        self.assertEqual(results[3]["status"], "INVALID_ZIP")
        self.assertEqual(results[4]["status"], "INVALID_ZIP")
        self.assertEqual(results[5]["status"], "INVALID_ZIP")
        self.assertEqual(results[6]["status"], "INVALID_ZIP")
        self.assertEqual(results[6]["zip_code"], "123-4567")
        self.assertEqual(mock_lookup.call_count, 2)

    @mock.patch("processor.services.time.sleep")
    @mock.patch("processor.services.requests.get")
    def test_lookup_zip_code_retries_timeouts_and_pauses(self, mock_get, mock_sleep):
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "places": [{"state": "Wisconsin", "state abbreviation": "WI"}]
        }

        mock_get.side_effect = [
            requests.exceptions.Timeout("timed out"),
            mock_response,
        ]

        result = lookup_zip_code("12345")

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["state"], "Wisconsin")
        self.assertEqual(result["state_abbreviation"], "WI")
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once_with(1)

    @mock.patch("processor.services.time.sleep")
    @mock.patch("processor.services.requests.get")
    def test_lookup_zip_code_does_not_retry_404(self, mock_get, mock_sleep):
        mock_response = mock.Mock()
        mock_response.status_code = 404

        mock_get.return_value = mock_response

        result = lookup_zip_code("12345")

        self.assertEqual(result["status"], "NOT_FOUND")
        self.assertEqual(mock_get.call_count, 1)
        mock_sleep.assert_not_called()

    @mock.patch("processor.services.time.sleep")
    @mock.patch("processor.services.requests.get")
    def test_lookup_zip_code_retries_429_and_5xx(self, mock_get, mock_sleep):
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "places": [{"state": "Nevada", "state abbreviation": "NV"}]
        }

        mock_get.side_effect = [
            mock.Mock(status_code=429),
            mock.Mock(status_code=503),
            mock_response,
        ]

        result = lookup_zip_code("12345")

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["state"], "Nevada")
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(mock_sleep.call_args_list, [mock.call(1), mock.call(2)])

    @mock.patch("processor.services.time.sleep")
    @mock.patch("processor.services.requests.get")
    def test_lookup_zip_code_stops_after_three_failed_attempts(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            mock.Mock(status_code=429),
            mock.Mock(status_code=429),
            mock.Mock(status_code=429),
        ]

        result = lookup_zip_code("12345")

        self.assertEqual(result["status"], "API_ERROR")
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(mock_sleep.call_args_list, [mock.call(1), mock.call(2)])

    @mock.patch("processor.services.time.sleep")
    @mock.patch("processor.services.requests.get")
    def test_lookup_zip_code_does_not_retry_other_4xx(self, mock_get, mock_sleep):
        mock_get.return_value = mock.Mock(status_code=400)

        result = lookup_zip_code("12345")

        self.assertEqual(result["status"], "API_ERROR")
        self.assertEqual(mock_get.call_count, 1)
        mock_sleep.assert_not_called()

    def test_write_results_csv_writes_expected_rows(self):
        temp_path = os.path.join(tempfile.gettempdir(), "processor_output_valid.csv")
        rows = [
            {"zip_code": "12345", "email": "user@example.com", "state": "California", "state_abbreviation": "CA", "status": "OK"},
            {"zip_code": "00042", "email": "other@example.com", "state": "Texas", "state_abbreviation": "TX", "status": "INVALID_EMAIL"},
        ]

        try:
            write_results_csv(temp_path, rows)
            with open(temp_path, "r", encoding="utf-8", newline="") as handle:
                csv_rows = list(csv.DictReader(handle))
            self.assertEqual(csv_rows, rows)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

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
