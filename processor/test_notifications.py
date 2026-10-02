from unittest import mock

from django.test import SimpleTestCase

from processor.notifications import send_result_notifications


class NotificationServiceTests(SimpleTestCase):
    def test_settings_have_console_email_and_data_defaults(self):
        from zipcode_notifier import settings

        self.assertEqual(
            settings.MAILERS["default"]["BACKEND"],
            "django.core.mail.backends.console.EmailBackend",
        )
        self.assertEqual(settings.MAILERS["default"]["OPTIONS"]["HOST"], "localhost")
        self.assertEqual(settings.MAILERS["default"]["OPTIONS"]["TIMEOUT"], 10)
        self.assertEqual(settings.INBOX_DIR.name, "inbox")
        self.assertEqual(settings.OUTPUT_DIR.name, "output")
        self.assertEqual(settings.PROCESSED_DIR.name, "processed")
        self.assertEqual(settings.ERROR_DIR.name, "error")
        self.assertEqual(settings.LOGS_DIR.name, "logs")

    @mock.patch("processor.notifications.send_mail")
    def test_send_result_notifications_groups_case_insensitive_email_addresses(self, mock_send):
        results = [
            {
                "zip_code": "12345",
                "email": " User@Example.com ",
                "state": "California",
                "state_abbreviation": "CA",
                "status": "OK",
            },
            {
                "zip_code": "00042",
                "email": "user@example.com",
                "state": "Texas",
                "state_abbreviation": "TX",
                "status": "INVALID_EMAIL",
            },
            {
                "zip_code": "54321",
                "email": "other@example.com",
                "state": "",
                "state_abbreviation": "",
                "status": "NOT_FOUND",
            },
            {
                "zip_code": "99999",
                "email": "bad-email",
                "state": "",
                "state_abbreviation": "",
                "status": "INVALID_EMAIL",
            },
        ]

        failed = send_result_notifications(results, "input.csv")

        self.assertEqual(failed, [])
        self.assertEqual(mock_send.call_count, 2)
        self.assertEqual(mock_send.call_args_list[0].args[3], ["User@Example.com"])
        self.assertIn("12345", mock_send.call_args_list[0].args[1])
        self.assertIn("00042", mock_send.call_args_list[0].args[1])
        self.assertEqual(mock_send.call_args_list[1].args[3], ["other@example.com"])

    @mock.patch("processor.notifications.send_mail")
    def test_send_result_notifications_returns_failed_addresses(self, mock_send):
        mock_send.side_effect = [Exception("SMTP failed"), None]
        results = [
            {
                "zip_code": "12345",
                "email": "first@example.com",
                "state": "California",
                "state_abbreviation": "CA",
                "status": "OK",
            },
            {
                "zip_code": "00042",
                "email": "second@example.com",
                "state": "Texas",
                "state_abbreviation": "TX",
                "status": "INVALID_EMAIL",
            },
        ]

        failed = send_result_notifications(results, "input.csv")

        self.assertEqual(failed, ["first@example.com"])
        self.assertEqual(mock_send.call_count, 2)
