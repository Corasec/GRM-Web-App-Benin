from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from authentication.factories import GovernmentWorkerFactory
from grm.tasks import escalate_issues, mark_issues_to_be_escalated
from grm.utils import reset_sequences
from issues.escalation import de_escalate_issue, escalate_issue
from issues.factories import (
    AdministrativeLevelFactory,
    AdministrativeRegionFactory,
    IssueCategoryFactory,
    IssueDepartmentAdministrativeLevelFactory,
    IssueDepartmentFactory,
    IssueFactory,
    IssueStatusFactory,
)
from issues.models import Comment, IssueStatusChange


@pytest.mark.django_db
@override_settings(LANGUAGE_CODE="en-us", CELERY_TASK_ALWAYS_EAGER=True)
class CommitteeEscalationTest(TestCase):
    """
    Escalation chain (COSO, Benin): CCGP (village) -> CLGP (commune) -> national committee.
    Tree: pays > departement > commune > arrondissement > village.
    """

    def setUp(self):
        reset_sequences()
        lvl = {
            name: AdministrativeLevelFactory(name=name)
            for name in ["pays", "departement", "commune", "arrondissement", "village"]
        }
        self.country = AdministrativeRegionFactory(name="Bénin", administrative_level=lvl["pays"], parent=None)
        self.departement = AdministrativeRegionFactory(administrative_level=lvl["departement"], parent=self.country)
        self.commune = AdministrativeRegionFactory(
            name="Malanville", administrative_level=lvl["commune"], parent=self.departement
        )
        self.other_commune = AdministrativeRegionFactory(administrative_level=lvl["commune"], parent=self.departement)
        self.arrondissement = AdministrativeRegionFactory(
            administrative_level=lvl["arrondissement"], parent=self.commune
        )
        self.village = AdministrativeRegionFactory(
            name="V1", administrative_level=lvl["village"], parent=self.arrondissement
        )
        self.other_village = AdministrativeRegionFactory(
            administrative_level=lvl["village"], parent=self.arrondissement
        )

        ccgp, clgp, national = (IssueDepartmentFactory(name=n) for n in ["CCGP", "CLGP", "Comité national"])
        ccgp_at_village = IssueDepartmentAdministrativeLevelFactory(
            department=ccgp, administrative_level=lvl["village"]
        )
        IssueDepartmentAdministrativeLevelFactory(department=clgp, administrative_level=lvl["commune"])
        IssueDepartmentAdministrativeLevelFactory(department=national, administrative_level=lvl["pays"])

        def committee(department, region):
            return GovernmentWorkerFactory(department=department, administrative_region=region).user

        self.ccgp = committee(ccgp, self.village)
        self.ccgp_other = committee(ccgp, self.other_village)
        self.clgp = committee(clgp, self.commune)
        self.clgp_other = committee(clgp, self.other_commune)
        self.national = committee(national, self.country)

        self.open_status = IssueStatusFactory(open_status=True, threshold_days=3, threshold_days_to_escalate=3)
        self.resolved_status = IssueStatusFactory(final_status=True)
        self.category = IssueCategoryFactory(assigned_department=ccgp_at_village)

    def _issue(self, assignee, **kwargs):
        defaults = dict(
            confirmed=True, category=self.category, administrative_region=self.village, status=self.open_status
        )
        defaults.update(kwargs)
        return IssueFactory(assignee=assignee, **defaults)

    # --- targets -------------------------------------------------------------------------------

    def test_escalation_chain_skips_arrondissement_and_departement(self):
        issue = self._issue(self.ccgp)

        assert escalate_issue(issue) == self.clgp
        assert escalate_issue(issue) == self.national
        assert escalate_issue(issue) is None  # top of the chain
        issue.refresh_from_db()
        assert issue.assignee == self.national

    def test_de_escalation_follows_the_issue_location(self):
        issue = self._issue(self.national)

        assert de_escalate_issue(issue) == self.clgp  # the commune of the issue, not another one
        assert de_escalate_issue(issue) == self.ccgp  # the village of the issue, not another one
        assert de_escalate_issue(issue) is None

    def test_closed_issue_is_not_escalated(self):
        issue = self._issue(self.ccgp, status=self.resolved_status)

        assert escalate_issue(issue) is None
        issue.refresh_from_db()
        assert issue.assignee == self.ccgp

    # --- trace and notification ----------------------------------------------------------------

    @patch("issues.escalation.send_issue_notification")
    def test_manual_escalation_leaves_a_trace_and_notifies_the_citizen(self, notify):
        issue = self._issue(self.ccgp)

        escalate_issue(issue, user=self.ccgp, reason="Conflit foncier hors de portée du village")

        issue.refresh_from_db()
        assert issue.escalated_date is not None
        assert issue.escalate_flag is False
        assert issue.escalation_reason == "Conflit foncier hors de portée du village"
        comment = Comment.objects.get(issue=issue)
        assert comment.user == self.ccgp
        assert self.clgp.name in comment.comment and "Conflit foncier" in comment.comment
        notify.assert_called_once_with(issue, "escalated")

    # --- automatic escalation ------------------------------------------------------------------

    def _overdue(self, issue, days):
        IssueStatusChange.objects.filter(issue=issue).update(entered_at=timezone.now() - timedelta(days=days))

    @patch("issues.escalation.send_issue_notification")
    def test_automatic_escalation_goes_one_committee_up(self, notify):
        issue = self._issue(self.ccgp)
        self._overdue(issue, days=5)

        assert mark_issues_to_be_escalated()["updated_issues"] == 1
        result = escalate_issues()

        issue.refresh_from_db()
        assert result["issues_updated"] == [issue.id]
        assert issue.assignee == self.clgp
        assert "processing time" in Comment.objects.get(issue=issue).comment
        notify.assert_called_once_with(issue, "escalated")

    @patch("issues.escalation.send_issue_notification")
    def test_escalated_issue_gets_a_full_period_at_its_new_committee(self, notify):
        """Regression: the counter was not reset, so the issue climbed one level per day up to the top."""
        issue = self._issue(self.ccgp)
        self._overdue(issue, days=5)
        mark_issues_to_be_escalated()
        escalate_issues()

        # Next day: still more than 3 days in the status, but escalated less than 3 days ago
        assert mark_issues_to_be_escalated()["updated_issues"] == 0
        issue.refresh_from_db()
        assert issue.assignee == self.clgp

        # Once the new period is over, it goes up again
        issue.__class__.objects.filter(pk=issue.pk).update(escalated_date=timezone.now() - timedelta(days=4))
        assert mark_issues_to_be_escalated()["updated_issues"] == 1
        escalate_issues()
        issue.refresh_from_db()
        assert issue.assignee == self.national

    @patch("issues.escalation.send_issue_notification")
    def test_failing_issue_does_not_block_the_automatic_escalation(self, notify):
        broken = self._issue(self.ccgp, escalate_flag=True)
        healthy = self._issue(self.ccgp_other, escalate_flag=True, administrative_region=self.other_village)

        original = type(broken).get_assignee_to_escalate

        def flaky(issue, region=None):
            if issue.pk == broken.pk:
                raise RuntimeError("boom")
            return original(issue, region)

        with patch.object(type(broken), "get_assignee_to_escalate", flaky):
            result = escalate_issues()

        healthy.refresh_from_db()
        assert result["errors"] == [broken.id]
        assert healthy.assignee == self.clgp

    def test_top_committee_issue_is_reported_as_not_escalable(self):
        issue = self._issue(self.national, escalate_flag=True)

        result = escalate_issues()

        assert result["scale_is_not_available"] == [issue.id]

    # --- mobile API: voluntary escalation --------------------------------------------------------

    def _patch_as(self, user, issue, data):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=user).key}")
        return client.patch(reverse("issues:update-issue", kwargs={"id": issue.id}), data, format="json")

    @patch("issues.escalation.send_issue_notification")
    def test_committee_escalation_from_the_app_is_immediate(self, notify):
        issue = self._issue(self.ccgp)

        response = self._patch_as(self.ccgp, issue, {"escalate_flag": True, "escalation_reason": "Hors compétence"})

        assert response.status_code == 200
        issue.refresh_from_db()
        assert issue.assignee == self.clgp  # the village committee loses the issue right away
        assert issue.escalate_flag is False
        assert issue.escalation_reason == "Hors compétence"
        notify.assert_called_once_with(issue, "escalated")

    def test_national_committee_cannot_escalate_from_the_app(self):
        issue = self._issue(self.national)

        response = self._patch_as(self.national, issue, {"escalate_flag": True, "escalation_reason": "x"})

        assert response.status_code == 400
        issue.refresh_from_db()
        assert issue.assignee == self.national
