from django.conf import settings
from django.core.management.base import BaseCommand

from processor.inbox import process_inbox


class Command(BaseCommand):
    help = "Process a single inbox scan and move files to processed or error folders."

    def add_arguments(self, parser):
        # Optional folder options let one run use different folders without changing .env.
        parser.add_argument("--inbox-dir", default=str(settings.INBOX_DIR), help="Directory containing inbox CSV files.")
        parser.add_argument("--output-dir", default=str(settings.OUTPUT_DIR), help="Directory where output CSV files are written.")
        parser.add_argument("--processed-dir", default=str(settings.PROCESSED_DIR), help="Directory for successfully processed input files.")
        parser.add_argument("--error-dir", default=str(settings.ERROR_DIR), help="Directory for invalid or failed input files.")

    def handle(self, *args, **options):
        # Use the same process_inbox function as the scheduler, so both handle files the same way.
        results = process_inbox(
            inbox_dir=options["inbox_dir"],
            output_dir=options["output_dir"],
            processed_dir=options["processed_dir"],
            error_dir=options["error_dir"],
        )

        if not results:
            # An empty inbox is normal, but print a message so it's clear that the scan ran.
            self.stdout.write(self.style.WARNING("No files found in the inbox."))
            return

        for result in results:
            if result["result"] == "processed":
                self.stdout.write(
                    self.style.SUCCESS(f"{result['file']}: processed -> {result['processed_path']}")
                )
            else:
                reason = result.get("reason", "unknown")
                self.stdout.write(
                    self.style.ERROR(f"{result['file']}: error -> {reason}")
                )
