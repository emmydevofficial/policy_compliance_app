"""The once-a-day command (SPEC 8). Run by cron or a systemd timer at 07:55 Lagos time.

python manage.py run_daily_notices [--dry-run] [--as-of YYYY-MM-DD]
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.notifications.services import run_daily


class Command(BaseCommand):
    help = "Mark overdue requests, create due notices and escalations, send pending notices."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be created and sent; write nothing.",
        )
        parser.add_argument("--as-of", default=None, help="Run as if today were YYYY-MM-DD.")

    def handle(self, *args, dry_run: bool, as_of: str | None, **opts):
        day = None
        if as_of:
            try:
                day = date.fromisoformat(as_of)
            except ValueError as exc:
                raise CommandError("--as-of must be YYYY-MM-DD") from exc
        report = run_daily(day, dry_run=dry_run)
        for line in report.lines():
            self.stdout.write(line)
