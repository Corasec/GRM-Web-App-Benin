from datetime import date, timedelta

import pytest
from django.test import TestCase
from django.utils import timezone

from authentication.factories import GovernmentWorkerFactory
from grm.tasks import mark_issues_to_be_escalated
from grm.utils import reset_sequences
from issues.deadlines import add_working_days, is_overdue, working_days_between
from issues.factories import (
    AdministrativeLevelFactory,
    AdministrativeRegionFactory,
    IssueCategoryFactory,
    IssueDepartmentAdministrativeLevelFactory,
    IssueDepartmentFactory,
    IssueFactory,
    IssueStatusFactory,
)
from issues.models import Issue

MONDAY = date(2026, 11, 23)


class WorkingDaysTest(TestCase):
    """Working days = Monday to Friday (public holidays are not handled)."""

    def test_add_working_days_skips_the_weekend(self):
        friday = MONDAY + timedelta(days=4)
        assert add_working_days(MONDAY, 3) == MONDAY + timedelta(days=3)  # Thursday
        assert add_working_days(friday, 1) == friday + timedelta(days=3)  # next Monday
        assert add_working_days(friday, 3) == friday + timedelta(days=5)  # next Wednesday

    def test_working_days_between(self):
        assert working_days_between(MONDAY, MONDAY) == 0
        assert working_days_between(MONDAY, MONDAY + timedelta(days=7)) == 5
        saturday = MONDAY + timedelta(days=5)
        assert working_days_between(saturday, saturday + timedelta(days=1)) == 0


@pytest.mark.django_db
class MarkIssuesToBeEscalatedTaskTest(TestCase):
    """Committee processing times (COSO): CCGP 3, CLGP 3, national 5 working days."""

    def setUp(self):
        reset_sequences()
        lvl_country, lvl_commune, lvl_village = (
            AdministrativeLevelFactory(name=n) for n in ["pays", "commune", "village"]
        )
        self.country = AdministrativeRegionFactory(administrative_level=lvl_country, parent=None)
        self.commune = AdministrativeRegionFactory(administrative_level=lvl_commune, parent=self.country)
        self.village = AdministrativeRegionFactory(administrative_level=lvl_village, parent=self.commune)

        ccgp = IssueDepartmentFactory(name="CCGP", processing_days=3)
        clgp = IssueDepartmentFactory(name="CLGP", processing_days=3)
        national = IssueDepartmentFactory(name="National", processing_days=5)
        ccgp_level = IssueDepartmentAdministrativeLevelFactory(department=ccgp, administrative_level=lvl_village)
        IssueDepartmentAdministrativeLevelFactory(department=clgp, administrative_level=lvl_commune)
        national_level = IssueDepartmentAdministrativeLevelFactory(
            department=national, administrative_level=lvl_country
        )

        self.ccgp = GovernmentWorkerFactory(department=ccgp, administrative_region=self.village).user
        GovernmentWorkerFactory(department=clgp, administrative_region=self.commune)
        self.national = GovernmentWorkerFactory(department=national, administrative_region=self.country).user

        self.open = IssueStatusFactory(open_status=True)
        self.resolved = IssueStatusFactory(final_status=True)
        self.category = IssueCategoryFactory(assigned_department=ccgp_level)
        self.gbv_category = IssueCategoryFactory(assigned_department=national_level, processing_days=22)

    def _issue(self, assignee, received_days_ago, **kwargs):
        defaults = dict(confirmed=True, category=self.category, administrative_region=self.village, status=self.open)
        defaults.update(kwargs)
        issue = IssueFactory(assignee=assignee, **defaults)
        Issue.objects.filter(pk=issue.pk).update(created_date=timezone.now() - timedelta(days=received_days_ago))
        issue.refresh_from_db()
        return issue

    def test_flags_issue_past_its_committee_deadline(self):
        issue = self._issue(self.ccgp, received_days_ago=10)

        result = mark_issues_to_be_escalated()

        issue.refresh_from_db()
        assert result["updated_issues"] == 1
        assert issue.escalate_flag is True

    def test_does_not_flag_issue_within_its_deadline(self):
        issue = self._issue(self.ccgp, received_days_ago=0)

        assert mark_issues_to_be_escalated()["updated_issues"] == 0
        issue.refresh_from_db()
        assert issue.escalate_flag is False

    def test_deadline_counts_from_the_last_escalation(self):
        issue = self._issue(self.ccgp, received_days_ago=30)
        Issue.objects.filter(pk=issue.pk).update(escalated_date=timezone.now())

        assert mark_issues_to_be_escalated()["updated_issues"] == 0

    def test_closed_issues_are_ignored(self):
        self._issue(self.ccgp, received_days_ago=30, status=self.resolved)

        assert mark_issues_to_be_escalated()["updated_issues"] == 0

    def test_committee_without_deadline_is_never_flagged(self):
        no_deadline = GovernmentWorkerFactory(
            department=IssueDepartmentFactory(processing_days=None), administrative_region=self.village
        ).user
        self._issue(no_deadline, received_days_ago=30)

        assert mark_issues_to_be_escalated()["updated_issues"] == 0

    def test_overdue_national_issue_is_only_reported(self):
        """No committee above the national one: the issue is shown as overdue, not escalated."""
        issue = self._issue(self.national, received_days_ago=45, category=self.gbv_category)

        result = mark_issues_to_be_escalated()

        issue.refresh_from_db()
        assert result["updated_issues"] == 0
        assert result["overdue_at_top"] == [issue.id]
        assert issue.escalate_flag is False
        assert issue.is_overdue is True

    def test_category_specific_time_replaces_the_committee_time(self):
        """GBV cases: 22 working days (about 30 calendar days) instead of 5 for the national committee."""
        issue = self._issue(self.national, received_days_ago=10, category=self.gbv_category)

        assert is_overdue(issue) is False
        assert mark_issues_to_be_escalated()["overdue_at_top"] == []
