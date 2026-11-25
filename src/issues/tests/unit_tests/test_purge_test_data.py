from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from authentication.factories import FacilitatorFactory, UserFactory
from authentication.models import Cdata, Pdata, User
from issues.factories import CitizenFactory, CommentFactory, IssueAttachmentFactory, IssueFactory
from issues.models import AdministrativeRegion, Citizen, Comment, Issue, IssueAttachment, IssueCategory
from wizard.importer import import_configuration
from wizard.tests.unit_tests.test_configuration_import import build_workbook

COMMAND = "issues.management.commands.purge_test_data"
# Real in-memory storage (the project test stub never reports files as existing)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
TODAY = timezone.localdate().isoformat()


@pytest.mark.django_db
@override_settings(STORAGES=STORAGES)
class PurgeTestDataTest(TestCase):
    def setUp(self):
        import_configuration(build_workbook())
        village = AdministrativeRegion.objects.filter(children=None).first()
        category = IssueCategory.objects.first()
        self.issue = IssueFactory(
            administrative_region=village,
            category=category,
            issue_type=category.parent.parent,
            issue_sub_type=category.parent,
            citizen=CitizenFactory(name="*"),
        )
        CommentFactory(issue=self.issue)
        self.attachment = IssueAttachmentFactory(issue=self.issue)
        self.file_name = self.attachment.file.name
        self.storage = self.attachment.file.storage
        Pdata.objects.create(key=str(self.issue.id), data="x")
        Cdata.objects.create(key=str(self.issue.id), data="y")
        self.facilitator = FacilitatorFactory(administrative_region=village)
        User.objects.filter(pk=self.facilitator.user.pk).update(is_active=False)

    def purge(self, *args, answer="PURGER"):
        with patch(f"{COMMAND}.input", return_value=answer):
            call_command("purge_test_data", "--until", TODAY, *args)

    def test_deletes_the_test_data_and_keeps_configuration_and_accounts(self):
        users = User.objects.count()
        categories = IssueCategory.objects.count()
        assert self.storage.exists(self.file_name)

        self.purge()

        assert not Issue.objects.exists()
        assert not Comment.objects.exists()
        assert not IssueAttachment.objects.exists()
        assert not Citizen.objects.exists()
        assert not Pdata.objects.exists() and not Cdata.objects.exists()
        assert not self.storage.exists(self.file_name)
        assert IssueCategory.objects.count() == categories
        assert User.objects.count() == users
        assert not User.objects.get(pk=self.facilitator.user.pk).is_active

    def test_reactivates_mobile_accounts_on_request(self):
        self.purge("--reactivate-accounts")

        assert User.objects.get(pk=self.facilitator.user.pk).is_active

    def test_dry_run_changes_nothing(self):
        call_command("purge_test_data", "--until", TODAY, "--dry-run")

        assert Issue.objects.count() == 1
        assert Pdata.objects.exists()

    def test_wrong_confirmation_changes_nothing(self):
        with pytest.raises(CommandError):
            self.purge(answer="oui")

        assert Issue.objects.count() == 1
        assert self.storage.exists(self.file_name)

    def test_refuses_when_issues_are_newer_than_the_test(self):
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()

        with pytest.raises(CommandError, match="Refused"):
            with patch(f"{COMMAND}.input", return_value="PURGER"):
                call_command("purge_test_data", "--until", yesterday)

        assert Issue.objects.count() == 1

    def test_until_must_be_a_date(self):
        with pytest.raises(CommandError):
            call_command("purge_test_data", "--until", "demain")
