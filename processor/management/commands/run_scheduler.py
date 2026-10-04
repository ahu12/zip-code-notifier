import logging
from threading import Event

from apscheduler.schedulers.background import BackgroundScheduler
from django.core.management.base import BaseCommand

from processor.inbox import process_inbox

logger = logging.getLogger(__name__)


def _stop_scheduler(scheduler):
    """Stop the scheduler only while it is still running."""
    if scheduler is None or not getattr(scheduler, "running", False):
        return
    scheduler.shutdown(wait=False)


def _run_inbox_scan(scheduler):
    """Run one inbox scan and stop the scheduler if a file cannot be moved out of the inbox."""
    logger.info("Starting inbox scan from scheduler.")
    try:
        process_inbox()
        logger.info("Inbox scan completed successfully.")
    except OSError:
        logger.exception(
            "A file could not be moved out of the inbox; the scheduler is stopping."
        )
        _stop_scheduler(scheduler)
        raise


class Command(BaseCommand):
    help = "Run the inbox scan on startup and then every two minutes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval-seconds",
            type=int,
            default=120,
            help="Seconds between inbox scans. Defaults to every two minutes.",
        )

    def handle(self, *args, **options):
        interval_seconds = options.get("interval_seconds", 120)
        logger.info("Scheduler starting. Inbox scans every %s seconds.", interval_seconds)

        # Use a background scheduler so Ctrl + C can stop the command right away
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _run_inbox_scan,
            "interval",
            seconds=interval_seconds,
            args=[scheduler],
            # DO not start a new scan while one is still running. If scans were missed, run just once.
            max_instances=1,
            coalesce=True,
        )

        try:
            # Scan once right away, then every 2 minutes after the initial scan.
            _run_inbox_scan(scheduler)
            scheduler.start()
            stop_wait = Event()
            # Wait in 1-second steps so Ctrl + C works quickly on Windows.
            while scheduler.running:
                stop_wait.wait(1)
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by keyboard interrupt.")
        except OSError:
            logger.exception("Scheduler stopped because an inbox file could not be moved.")
            _stop_scheduler(scheduler)
            raise
        finally:
            _stop_scheduler(scheduler)
            logger.info("Scheduler stopped.")
