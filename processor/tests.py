import csv
import os
import tempfile
from unittest import mock

import requests
from django.test import SimpleTestCase

from processor.inbox import process_inbox
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

    def test_write_results_csv_escapes_formula_prefixes_in_output(self):
        temp_path = os.path.join(tempfile.gettempdir(), "processor_output_formula.csv")
        rows = [
            {
                "zip_code": "=SUM(A1:A2)",
                "email": "+not_a_command",
                "state": "-danger",
                "state_abbreviation": "@user",
                "status": "\tVISIBLE",
            },
            {
                "zip_code": "\rBOT",
                "email": "safe@example.com",
                "state": "California",
                "state_abbreviation": "CA",
                "status": "OK",
            },
        ]

        try:
            write_results_csv(temp_path, rows)
            with open(temp_path, "r", encoding="utf-8", newline="") as handle:
                csv_rows = list(csv.DictReader(handle))
            self.assertEqual(csv_rows[0]["zip_code"], "'=SUM(A1:A2)")
            self.assertEqual(csv_rows[0]["email"], "'+not_a_command")
            self.assertEqual(csv_rows[0]["state"], "'-danger")
            self.assertEqual(csv_rows[0]["state_abbreviation"], "'@user")
            self.assertEqual(csv_rows[0]["status"], "'\tVISIBLE")
            self.assertEqual(csv_rows[1]["zip_code"], "'\rBOT")
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_write_results_csv_keeps_safe_values_unchanged(self):
        temp_path = os.path.join(tempfile.gettempdir(), "processor_output_safe.csv")
        rows = [
            {
                "zip_code": "02108",
                "email": "user@example.com",
                "state": "California",
                "state_abbreviation": "CA",
                "status": "OK",
            }
        ]

        try:
            write_results_csv(temp_path, rows)
            with open(temp_path, "r", encoding="utf-8", newline="") as handle:
                csv_rows = list(csv.DictReader(handle))
            self.assertEqual(csv_rows[0]["zip_code"], "02108")
            self.assertEqual(csv_rows[0]["email"], "user@example.com")
            self.assertEqual(csv_rows[0]["state"], "California")
            self.assertEqual(csv_rows[0]["state_abbreviation"], "CA")
            self.assertEqual(csv_rows[0]["status"], "OK")
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


class InboxProcessingTests(SimpleTestCase):
    @mock.patch("processor.inbox.send_result_notifications", return_value=[])
    @mock.patch("processor.services.lookup_zip_code")
    def test_process_inbox_moves_valid_file_to_processed_and_writes_output(self, mock_lookup, mock_notifications):
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox_dir = os.path.join(tmpdir, "inbox")
            output_dir = os.path.join(tmpdir, "output")
            processed_dir = os.path.join(tmpdir, "processed")
            error_dir = os.path.join(tmpdir, "error")
            for directory in (inbox_dir, output_dir, processed_dir, error_dir):
                os.makedirs(directory, exist_ok=True)

            input_path = os.path.join(inbox_dir, "input.csv")
            with open(input_path, "w", encoding="utf-8", newline="") as handle:
                handle.write("zip_code,email\n12345,user@example.com\n")

            mock_lookup.return_value = {
                "zip_code": "12345",
                "state": "California",
                "state_abbreviation": "CA",
                "status": "OK",
            }

            process_inbox(inbox_dir, output_dir, processed_dir, error_dir)

            self.assertFalse(os.path.exists(input_path))
            processed_files = os.listdir(processed_dir)
            self.assertEqual(len(processed_files), 1)
            self.assertIn("input", processed_files[0])
            self.assertEqual(len(os.listdir(output_dir)), 1)
            self.assertTrue(mock_notifications.called)

    @mock.patch("processor.inbox.send_result_notifications", return_value=["user@example.com"])
    @mock.patch("processor.services.lookup_zip_code")
    def test_process_inbox_moves_email_failures_to_error(self, mock_lookup, mock_notifications):
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox_dir = os.path.join(tmpdir, "inbox")
            output_dir = os.path.join(tmpdir, "output")
            processed_dir = os.path.join(tmpdir, "processed")
            error_dir = os.path.join(tmpdir, "error")
            for directory in (inbox_dir, output_dir, processed_dir, error_dir):
                os.makedirs(directory, exist_ok=True)

            input_path = os.path.join(inbox_dir, "email_fail.csv")
            with open(input_path, "w", encoding="utf-8", newline="") as handle:
                handle.write("zip_code,email\n12345,user@example.com\n")

            mock_lookup.return_value = {
                "zip_code": "12345",
                "state": "California",
                "state_abbreviation": "CA",
                "status": "OK",
            }

            process_inbox(inbox_dir, output_dir, processed_dir, error_dir)

            self.assertFalse(os.path.exists(input_path))
            self.assertEqual(len(os.listdir(error_dir)), 1)
            self.assertEqual(len(os.listdir(output_dir)), 1)
            self.assertEqual(len(os.listdir(processed_dir)), 0)
            self.assertTrue(mock_notifications.called)

    @mock.patch("processor.inbox.send_result_notifications")
    @mock.patch("processor.services.lookup_zip_code")
    def test_process_inbox_moves_invalid_csv_to_error(self, mock_lookup, mock_notifications):
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox_dir = os.path.join(tmpdir, "inbox")
            output_dir = os.path.join(tmpdir, "output")
            processed_dir = os.path.join(tmpdir, "processed")
            error_dir = os.path.join(tmpdir, "error")
            for directory in (inbox_dir, output_dir, processed_dir, error_dir):
                os.makedirs(directory, exist_ok=True)

            input_path = os.path.join(inbox_dir, "invalid.csv")
            with open(input_path, "w", encoding="utf-8", newline="") as handle:
                handle.write("email\nuser@example.com\n")

            process_inbox(inbox_dir, output_dir, processed_dir, error_dir)

            self.assertFalse(os.path.exists(input_path))
            self.assertEqual(len(os.listdir(error_dir)), 1)
            self.assertEqual(len(os.listdir(output_dir)), 0)
            self.assertEqual(len(os.listdir(processed_dir)), 0)
            mock_lookup.assert_not_called()
            mock_notifications.assert_not_called()

    @mock.patch("processor.inbox.send_result_notifications")
    @mock.patch("processor.inbox.write_results_csv", side_effect=OSError("disk full"))
    @mock.patch("processor.services.lookup_zip_code")
    def test_process_inbox_writing_output_failure_sends_no_emails_and_moves_file_to_error(
        self, mock_lookup, mock_write_output, mock_notifications
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox_dir = os.path.join(tmpdir, "inbox")
            output_dir = os.path.join(tmpdir, "output")
            processed_dir = os.path.join(tmpdir, "processed")
            error_dir = os.path.join(tmpdir, "error")
            for directory in (inbox_dir, output_dir, processed_dir, error_dir):
                os.makedirs(directory, exist_ok=True)

            input_path = os.path.join(inbox_dir, "write_fail.csv")
            with open(input_path, "w", encoding="utf-8", newline="") as handle:
                handle.write("zip_code,email\n12345,user@example.com\n")

            mock_lookup.return_value = {
                "zip_code": "12345",
                "state": "California",
                "state_abbreviation": "CA",
                "status": "OK",
            }

            process_inbox(inbox_dir, output_dir, processed_dir, error_dir)

            self.assertFalse(os.path.exists(input_path))
            self.assertEqual(len(os.listdir(error_dir)), 1)
            self.assertEqual(len(os.listdir(output_dir)), 0)
            self.assertEqual(len(os.listdir(processed_dir)), 0)
            mock_notifications.assert_not_called()

    @mock.patch("processor.inbox.send_result_notifications", return_value=[])
    @mock.patch("processor.inbox.read_input_csv")
    @mock.patch("processor.services.lookup_zip_code")
    def test_process_inbox_continues_after_unexpected_error_on_one_file(
        self, mock_lookup, mock_read_input_csv, mock_notifications
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox_dir = os.path.join(tmpdir, "inbox")
            output_dir = os.path.join(tmpdir, "output")
            processed_dir = os.path.join(tmpdir, "processed")
            error_dir = os.path.join(tmpdir, "error")
            for directory in (inbox_dir, output_dir, processed_dir, error_dir):
                os.makedirs(directory, exist_ok=True)

            bad_path = os.path.join(inbox_dir, "bad.csv")
            good_path = os.path.join(inbox_dir, "good.csv")
            for path, content in (
                (bad_path, "zip_code,email\n12345,user@example.com\n"),
                (good_path, "zip_code,email\n54321,other@example.com\n"),
            ):
                with open(path, "w", encoding="utf-8", newline="") as handle:
                    handle.write(content)

            mock_read_input_csv.side_effect = [RuntimeError("unexpected failure"), [{"zip_code": "54321", "email": "other@example.com"}]]
            mock_lookup.return_value = {
                "zip_code": "54321",
                "state": "Texas",
                "state_abbreviation": "TX",
                "status": "OK",
            }

            process_inbox(inbox_dir, output_dir, processed_dir, error_dir)

            self.assertEqual(len(os.listdir(error_dir)), 1)
            self.assertEqual(len(os.listdir(processed_dir)), 1)
            self.assertEqual(len(os.listdir(output_dir)), 1)
            self.assertTrue(mock_notifications.called)

    @mock.patch("processor.inbox.send_result_notifications", return_value=[])
    @mock.patch("processor.inbox._move_file_to_directory", side_effect=OSError("move failed"))
    @mock.patch("processor.services.lookup_zip_code")
    def test_process_inbox_stops_when_moving_file_fails_and_keeps_output_and_input(
        self, mock_lookup, mock_move, mock_notifications
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox_dir = os.path.join(tmpdir, "inbox")
            output_dir = os.path.join(tmpdir, "output")
            processed_dir = os.path.join(tmpdir, "processed")
            error_dir = os.path.join(tmpdir, "error")
            for directory in (inbox_dir, output_dir, processed_dir, error_dir):
                os.makedirs(directory, exist_ok=True)

            input_path = os.path.join(inbox_dir, "move_fail.csv")
            with open(input_path, "w", encoding="utf-8", newline="") as handle:
                handle.write("zip_code,email\n12345,user@example.com\n")

            mock_lookup.return_value = {
                "zip_code": "12345",
                "state": "California",
                "state_abbreviation": "CA",
                "status": "OK",
            }

            with self.assertRaises(OSError):
                process_inbox(inbox_dir, output_dir, processed_dir, error_dir)

            self.assertTrue(os.path.exists(input_path))
            self.assertEqual(len(os.listdir(inbox_dir)), 1)
            self.assertEqual(len(os.listdir(output_dir)), 1)
            self.assertEqual(len(os.listdir(processed_dir)), 0)
            self.assertEqual(len(os.listdir(error_dir)), 0)
            mock_notifications.assert_called_once()

    def test_process_inbox_ignores_non_csv_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inbox_dir = os.path.join(tmpdir, "inbox")
            output_dir = os.path.join(tmpdir, "output")
            processed_dir = os.path.join(tmpdir, "processed")
            error_dir = os.path.join(tmpdir, "error")
            for directory in (inbox_dir, output_dir, processed_dir, error_dir):
                os.makedirs(directory, exist_ok=True)

            text_path = os.path.join(inbox_dir, "notes.txt")
            with open(text_path, "w", encoding="utf-8") as handle:
                handle.write("ignore me")

            results = process_inbox(inbox_dir, output_dir, processed_dir, error_dir)

            self.assertEqual(results, [])
            self.assertTrue(os.path.exists(text_path))
            self.assertEqual(os.listdir(inbox_dir), ["notes.txt"])
            self.assertEqual(len(os.listdir(output_dir)), 0)
            self.assertEqual(len(os.listdir(processed_dir)), 0)
            self.assertEqual(len(os.listdir(error_dir)), 0)


class SchedulerCommandTests(SimpleTestCase):
    @mock.patch("processor.management.commands.run_scheduler.BackgroundScheduler")
    @mock.patch("processor.management.commands.run_scheduler.process_inbox")
    def test_run_scheduler_starts_scan_immediately_and_schedules_interval(self, mock_process_inbox, mock_scheduler_cls):
        mock_scheduler = mock.Mock()
        mock_scheduler.running = True
        mock_scheduler.start.side_effect = KeyboardInterrupt
        mock_scheduler_cls.return_value = mock_scheduler

        from processor.management.commands.run_scheduler import Command

        Command().handle()

        self.assertEqual(mock_process_inbox.call_count, 1)
        mock_scheduler.add_job.assert_called_once()
        self.assertEqual(mock_scheduler.add_job.call_args.kwargs["seconds"], 120)
        mock_scheduler.start.assert_called_once()

    @mock.patch("processor.management.commands.run_scheduler.BackgroundScheduler")
    @mock.patch("processor.management.commands.run_scheduler.process_inbox", side_effect=OSError("move failed"))
    def test_run_scheduler_shuts_down_when_scan_move_fails(self, mock_process_inbox, mock_scheduler_cls):
        mock_scheduler = mock.Mock()
        mock_scheduler.running = True
        mock_scheduler_cls.return_value = mock_scheduler

        from processor.management.commands.run_scheduler import Command

        with self.assertRaises(OSError):
            Command().handle()

        mock_process_inbox.assert_called_once()

    @mock.patch("processor.management.commands.run_scheduler.BackgroundScheduler")
    @mock.patch("processor.management.commands.run_scheduler.process_inbox")
    def test_scheduled_scan_move_failure_stops_scheduler(self, mock_process_inbox, mock_scheduler_cls):
        mock_scheduler = mock.Mock()
        mock_scheduler.running = True
        mock_scheduler.start.side_effect = lambda: setattr(mock_scheduler, "running", False)
        mock_scheduler_cls.return_value = mock_scheduler

        from processor.management.commands.run_scheduler import Command

        Command().handle()
        scheduled_scan = mock_scheduler.add_job.call_args.args[0]
        mock_process_inbox.reset_mock()
        mock_process_inbox.side_effect = OSError("move failed")
        mock_scheduler.running = True

        with self.assertRaises(OSError):
            scheduled_scan(mock_scheduler)

        mock_process_inbox.assert_called_once()
        mock_scheduler.shutdown.assert_called_once_with(wait=False)
