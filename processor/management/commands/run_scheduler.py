import logging
from threading import Event

from apscheduler.schedulers.background import BackgroundScheduler
from django.core.management.base import BaseCommand

from processor.inbox import process_inbox

logger = logging.getLogger(__name__)


def _stop_scheduler(scheduler):
    """Shutdown the scheduler once to prevent a repeated stop loop."""
    if scheduler is None or getattr(scheduler, "_shutdown_triggered", False) is True:
        return
    if getattr(scheduler, "running", False):
        scheduler._shutdown_triggered = True
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

        # A background scheduler lets the command wait interruptibly instead of blocking in APScheduler.
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _run_inbox_scan,
            "interval",
            seconds=interval_seconds,
            args=[scheduler],
            # Do not start another scan while a slow scan is still running; coalesce missed ticks.
            max_instances=1,
            coalesce=True,
        )

        try:
            # Process existing files immediately; the interval job handles subsequent arrivals.
            _run_inbox_scan(scheduler)
            scheduler.start()
            stop_wait = Event()
            # Polling the event makes Windows Ctrl+C responsive even when the next tick is far away.
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
