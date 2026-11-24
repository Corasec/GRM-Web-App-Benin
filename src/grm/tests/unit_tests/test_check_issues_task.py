from unittest.mock import patch

import pytest
from django.test import TestCase, override_settings

from authentication.models import Cdata, Pdata
from grm.tasks import check_issues
from grm.utils import reset_sequences
from issues.factories import (
    AdministrativeRegionFactory,
    CitizenFactory,
    IssueCategoryFactory,
    IssueFactory,
    UserFactory,
)
from issues.models import Comment, Issue


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class CheckIssuesTaskTest(TestCase):
    """
    `check_issues` backfills, for every confirmed issue, the internal code, the
    anonymisation of the citizen name / contact and the assignee.

    `Issue.get_assignee` is mocked: the routing rule itself is tested separately
    (it is being rewritten, see backlog item 1b). These tests cover the task.
    """

    def setUp(self):
        reset_sequences()

    def _pending_issue(self, **kwargs):
        """A confirmed issue still needing every backfill step."""
        defaults = dict(
            confirmed=True,
            assignee=None,
            internal_code=None,
            citizen=None,
            contact_information=None,
        )
        defaults.update(kwargs)
        return IssueFactory(**defaults)

    def test_task_runs_without_query_error(self):
        """Regression: the queryset used to reference nonexistent fields (FieldError)."""
        result = check_issues()

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["updated_issues"], 0)

    def test_sets_internal_code(self):
        category = IssueCategoryFactory(abbreviation="ABC")
        issue = self._pending_issue(category=category)

        with patch.object(Issue, "get_assignee", return_value=None):
            result = check_issues()

        issue.refresh_from_db()
        self.assertEqual(issue.internal_code, f"ABC-{issue.administrative_region_id}-{issue.id}")
        self.assertIn(issue.id, result["internal_code_updated"])
        self.assertEqual(result["updated_issues"], 1)

    def test_assigns_issue_and_adds_system_comment(self):
        committee = UserFactory()
        issue = self._pending_issue()

        with patch.object(Issue, "get_assignee", return_value=committee):
            result = check_issues()

        issue.refresh_from_db()
        self.assertEqual(issue.assignee, committee)
        self.assertIn(issue.id, result["assignee_updated"])
        comment = Comment.objects.get(issue=issue)
        self.assertIsNone(comment.user)
        self.assertIn(committee.name, comment.comment)

    def test_no_assignee_found_leaves_issue_unassigned_without_comment(self):
        issue = self._pending_issue()

        with patch.object(Issue, "get_assignee", return_value=None):
            result = check_issues()

        issue.refresh_from_db()
        self.assertIsNone(issue.assignee)
        self.assertNotIn(issue.id, result["assignee_updated"])
        self.assertFalse(Comment.objects.filter(issue=issue).exists())
        self.assertEqual(result["errors"], [])

    def test_anonymizes_citizen_name_and_contact(self):
        citizen = CitizenFactory(name="Awa Koné")
        issue = self._pending_issue(citizen=citizen, contact_information="+22990000000")

        with patch.object(Issue, "get_assignee", return_value=None):
            result = check_issues()

        issue.refresh_from_db()
        citizen.refresh_from_db()
        self.assertEqual(citizen.name, "*")
        self.assertEqual(issue.contact_information, "*")
        self.assertTrue(Pdata.objects.filter(key=str(issue.id)).exists())
        self.assertTrue(Cdata.objects.filter(key=str(issue.id)).exists())
        self.assertIn(issue.id, result["anonymized_data"])

    def test_unconfirmed_issues_are_ignored(self):
        issue = self._pending_issue(confirmed=False)

        with patch.object(Issue, "get_assignee", return_value=UserFactory()) as get_assignee:
            result = check_issues()

        issue.refresh_from_db()
        get_assignee.assert_not_called()
        self.assertIsNone(issue.assignee)
        self.assertIsNone(issue.internal_code)
        self.assertEqual(result["updated_issues"], 0)

    def test_fully_processed_issue_is_not_selected_again(self):
        citizen = CitizenFactory(name="Awa Koné")
        self._pending_issue(citizen=citizen, contact_information="+22990000000")

        with patch.object(Issue, "get_assignee", return_value=UserFactory()):
            first = check_issues()
        with patch.object(Issue, "get_assignee") as get_assignee:
            second = check_issues()

        self.assertEqual(first["updated_issues"], 1)
        self.assertEqual(second["updated_issues"], 0)
        get_assignee.assert_not_called()

    def test_already_complete_issue_with_citizen_is_not_selected(self):
        """Regression: any issue with a citizen used to be re-selected forever."""
        IssueFactory(
            confirmed=True,
            assignee=UserFactory(),
            internal_code="ABC-1-1",
            citizen=CitizenFactory(name="*"),
            contact_information="*",
        )

        with patch.object(Issue, "get_assignee") as get_assignee:
            result = check_issues()

        get_assignee.assert_not_called()
        self.assertEqual(result["updated_issues"], 0)

    def test_failing_issue_does_not_block_the_others(self):
        """An issue without category cannot get an internal code; the next ones must still be processed."""
        region = AdministrativeRegionFactory()
        broken = self._pending_issue(category=None, administrative_region=region)
        healthy = self._pending_issue(administrative_region=region)
        committee = UserFactory()

        def fake_get_assignee(issue):
            if issue.category is None:
                raise AttributeError("no category")
            return committee

        with patch.object(Issue, "get_assignee", autospec=True, side_effect=fake_get_assignee):
            result = check_issues()

        healthy.refresh_from_db()
        broken.refresh_from_db()
        self.assertEqual(healthy.assignee, committee)
        self.assertIsNotNone(healthy.internal_code)
        self.assertIsNone(broken.assignee)
        self.assertTrue(any(str(broken.id) in error for error in result["errors"]))

    def test_assignee_error_still_saves_other_backfills(self):
        issue = self._pending_issue()

        with patch.object(Issue, "get_assignee", side_effect=RuntimeError("boom")):
            result = check_issues()

        issue.refresh_from_db()
        self.assertIsNotNone(issue.internal_code)
        self.assertIsNone(issue.assignee)
        self.assertTrue(any(str(issue.id) in error for error in result["errors"]))
