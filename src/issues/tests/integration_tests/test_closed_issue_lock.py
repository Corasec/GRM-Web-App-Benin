from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from grm.constants import ESCALATION_NOT_ACCEPTED_MESSAGE, ISSUE_CLOSED_ERROR_MESSAGE
from grm.test_storage import IN_MEMORY_STORAGES
from grm.utils import reset_sequences
from issues.factories import CommentFactory, IssueFactory, IssueStatusFactory, UserFactory
from issues.models import Comment, Issue, IssueAttachment


@pytest.mark.django_db
@override_settings(STORAGES=IN_MEMORY_STORAGES, LANGUAGE_CODE="en-us")
class ClosedIssueLockTest(TestCase):
    """
    COSO rules: a resolved or rejected issue can no longer be modified by the committee
    (status, comments/steps, attachments); the committee must accept an issue before escalating it.
    """

    def setUp(self):
        reset_sequences()
        self.committee = UserFactory()
        self.reporter = UserFactory()
        self.initial = IssueStatusFactory(initial_status=True)
        self.open = IssueStatusFactory(open_status=True)
        self.resolved = IssueStatusFactory(final_status=True)
        self.issue = IssueFactory(assignee=self.committee, reporter=self.reporter, status=self.open, confirmed=True)

    def _client(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.get_or_create(user=user)[0].key}")
        return client

    def _close(self, closed_ago=timedelta(hours=2)):
        self.issue.status = self.resolved
        self.issue.save()
        Issue.objects.filter(pk=self.issue.pk).update(resolution_date=timezone.now() - closed_ago)
        self.issue.refresh_from_db()

    def _add_comment(self, user):
        url = reverse("issues:add-issue-comment", kwargs={"id": self.issue.id})
        return self._client(user).post(url, {"comment": "Nouvelle étape"}, format="json")

    def _add_attachment(self, user):
        url = reverse("issues:add-issue-attachment", kwargs={"id": self.issue.id})
        file = SimpleUploadedFile(name="proof.txt", content=b"x", content_type="text/plain")
        return self._client(user).post(url, {"file": file}, format="multipart")

    def _patch(self, user, data):
        url = reverse("issues:update-issue", kwargs={"id": self.issue.id})
        return self._client(user).patch(url, data, format="json")

    # --- status and fields -----------------------------------------------------------------------

    def test_committee_cannot_change_a_resolved_issue(self):
        self._close()

        response = self._patch(self.committee, {"status": self.open.id})

        assert response.status_code == 400
        assert str(ISSUE_CLOSED_ERROR_MESSAGE) in str(response.data["errors"])
        self.issue.refresh_from_db()
        assert self.issue.status == self.resolved

    def test_reporter_can_still_rate_a_resolved_issue(self):
        self._close()

        response = self._patch(self.reporter, {"rating": 4})

        assert response.status_code == 200
        self.issue.refresh_from_db()
        assert self.issue.rating == 4

    # --- comments and attachments ----------------------------------------------------------------

    def test_no_new_step_on_a_closed_issue(self):
        self._close()

        response = self._add_comment(self.committee)

        assert response.status_code == 403
        assert not Comment.objects.filter(issue=self.issue).exists()

    def test_no_new_attachment_on_a_closed_issue(self):
        self._close()

        response = self._add_attachment(self.committee)

        assert response.status_code == 403
        assert not IssueAttachment.objects.filter(issue=self.issue).exists()

    def test_closing_committee_can_send_the_closing_comment_and_files_right_after(self):
        """The app sends the reason / resolution comment and files just after the status change."""
        self._close(closed_ago=timedelta(minutes=2))

        assert self._add_comment(self.committee).status_code == 201
        assert self._add_attachment(self.committee).status_code == 201

    def test_grace_period_is_only_for_the_closing_committee(self):
        self._close(closed_ago=timedelta(minutes=2))

        assert self._add_comment(self.reporter).status_code == 403

    def test_no_deletion_on_a_closed_issue(self):
        comment = CommentFactory(issue=self.issue, user=self.committee)
        self._close(closed_ago=timedelta(minutes=2))

        url = reverse("issues:delete-issue-comment", kwargs={"id": comment.id})
        response = self._client(self.committee).delete(url)

        assert response.status_code == 403
        assert Comment.objects.filter(pk=comment.pk).exists()

    def test_open_issue_accepts_steps(self):
        assert self._add_comment(self.committee).status_code == 201

    # --- escalation requires acceptance ------------------------------------------------------------

    def test_committee_must_accept_before_escalating(self):
        self.issue.status = self.initial
        self.issue.save()

        response = self._patch(self.committee, {"escalate_flag": True, "escalation_reason": "Hors compétence"})

        assert response.status_code == 400
        assert str(ESCALATION_NOT_ACCEPTED_MESSAGE) in str(response.data["errors"])
        self.issue.refresh_from_db()
        assert self.issue.escalate_flag is False
        assert self.issue.assignee == self.committee
