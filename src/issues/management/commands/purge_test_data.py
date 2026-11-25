"""
Remove the data created during the field acceptance test, before opening the GRM to the public.

Deletes every issue with its history, comments and attachments (files included), the encrypted
complainant names / contacts, the complainants created with the issues, the notification logs of
the issues and the dashboard statistics. Keeps the configuration (wizard, categorisation) and the
accounts. Optionally reactivates the mobile accounts deactivated during the test.

Safety: ``--until`` (last day of the test) is required and the command refuses to run when an
issue or a comment is more recent: it can never wipe real issues after the launch. It shows what
it will delete and asks to type PURGER.

    python manage.py purge_test_data --until 2026-12-05 [--reactivate-accounts] [--dry-run]
"""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Q

from authentication.models import Cdata, Pdata, User
from dashboard.models import PerformanceMetrics, RegionPerformanceMetrics, StatusBottleneckMetrics
from integrations.models import NotificationLog
from issues.models import Citizen, Comment, Issue, IssueAttachment, IssueStatusChange

CONFIRMATION = "PURGER"
# Emptied tables whose ids restart at 1, so that the first real issue is number 1 (PostgreSQL only)
RESET_SEQUENCES = [Issue, Comment, IssueAttachment, IssueStatusChange, Citizen]


class Command(BaseCommand):
    help = "Delete the issues and related data of the field acceptance test (keeps configuration and accounts)."

    def add_arguments(self, parser):
        parser.add_argument("--until", required=True, help="Last day of the test (YYYY-MM-DD).")
        parser.add_argument(
            "--reactivate-accounts",
            action="store_true",
            help="Reactivate the committee and field staff accounts deactivated during the test.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted, change nothing.")

    def handle(self, *args, **options):
        try:
            until = datetime.strptime(options["until"], "%Y-%m-%d").date()
        except ValueError:
            raise CommandError("--until must be a date YYYY-MM-DD (last day of the test).")

        newer_issues = Issue.objects.filter(created_date__date__gt=until).count()
        newer_comments = Comment.objects.filter(created_date__date__gt=until).count()
        if newer_issues or newer_comments:
            raise CommandError(
                f"Refused: {newer_issues} issue(s) and {newer_comments} comment(s) were created after {until}. "
                "They may be real issues: nothing was deleted."
            )

        issues = Issue.objects.all()
        citizens = Citizen.objects.filter(citizen_issues__isnull=False, user_citizen__isnull=True).distinct()
        inactive_accounts = User.objects.filter(is_active=False).filter(
            Q(governmentworker__isnull=False) | Q(facilitator__isnull=False)
        )
        plan = [
            ("issues", issues.count()),
            ("status changes", IssueStatusChange.objects.count()),
            ("comments", Comment.objects.count()),
            ("attachments (files included)", IssueAttachment.objects.count()),
            ("complainants", citizens.count()),
            ("encrypted names / contacts", Pdata.objects.count() + Cdata.objects.count()),
            ("notification logs", NotificationLog.objects.filter(issue__isnull=False).count()),
            (
                "dashboard statistics",
                PerformanceMetrics.objects.count()
                + StatusBottleneckMetrics.objects.count()
                + RegionPerformanceMetrics.objects.count(),
            ),
        ]
        self.stdout.write(f"Test data up to {until}:")
        for label, count in plan:
            self.stdout.write(f"  - {label}: {count}")
        self.stdout.write("Kept: configuration, categorisation, accounts.")
        if inactive_accounts.exists():
            action = (
                "will be reactivated" if options["reactivate_accounts"] else "stay inactive (--reactivate-accounts)"
            )
            self.stdout.write(f"Inactive mobile accounts ({action}):")
            for email in inactive_accounts.values_list("email", flat=True):
                self.stdout.write(f"  - {email}")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: nothing was changed."))
            return
        if input(f"Type {CONFIRMATION} to delete this data: ").strip() != CONFIRMATION:
            raise CommandError("Not confirmed: nothing was deleted.")

        files = [a.file for a in IssueAttachment.objects.exclude(file="").exclude(file__isnull=True)]
        with transaction.atomic():
            NotificationLog.objects.filter(issue__isnull=False).delete()
            citizen_ids = list(citizens.values_list("id", flat=True))
            issues.delete()  # cascades to status changes, comments and attachments
            Citizen.objects.filter(id__in=citizen_ids).delete()
            Pdata.objects.all().delete()
            Cdata.objects.all().delete()
            PerformanceMetrics.objects.all().delete()
            StatusBottleneckMetrics.objects.all().delete()
            RegionPerformanceMetrics.objects.all().delete()
            reactivated = inactive_accounts.update(is_active=True) if options["reactivate_accounts"] else 0
        removed_files = 0
        for file in files:
            try:
                file.storage.delete(file.name)
                removed_files += 1
            except Exception as error:  # a missing file must not stop the purge
                self.stderr.write(f"Could not delete {file.name}: {error}")
        self._reset_sequences()

        self.stdout.write(
            self.style.SUCCESS(
                f"Test data deleted ({removed_files} file(s) removed, {reactivated} account(s) reactivated). "
                "Clear the app data on the test phones: they still hold the test issues locally."
            )
        )

    @staticmethod
    def _reset_sequences():
        if connection.vendor != "postgresql":
            return
        with connection.cursor() as cursor:
            for model in RESET_SEQUENCES:
                if not model.objects.exists():
                    table = model._meta.db_table
                    cursor.execute("SELECT setval(pg_get_serial_sequence(%s, 'id'), 1, false)", [table])
