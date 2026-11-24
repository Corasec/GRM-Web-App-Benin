import pytest
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from grm.constants import ALERT_CHOICE, PHONE_CHOICE
from grm.utils import reset_sequences
from issues.factories import CitizenFactory, IssueFactory, UserFactory
from issues.models import Issue


@pytest.mark.django_db
@override_settings(LANGUAGE_CODE="en-us")
class ComplainantInAppTest(TestCase):
    """The committee handling an issue and its reporter see the complainant's name and contact in the app."""

    def setUp(self):
        reset_sequences()
        self.committee = UserFactory()
        self.reporter = UserFactory()
        self.issue = IssueFactory(
            assignee=self.committee,
            reporter=self.reporter,
            confirmed=True,
            citizen=CitizenFactory(name="Awa Koné", gender="female"),
            contact_medium=ALERT_CHOICE,
            contact_method=PHONE_CHOICE,
            contact_information="+2290197000000",
        )
        self.issue.anonymize_issue_data()
        self.issue.save()

    def _get(self, user, url):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.get_or_create(user=user)[0].key}")
        return client.get(url)

    def test_stored_issue_keeps_only_anonymised_values(self):
        stored = Issue.objects.select_related("citizen").get(pk=self.issue.pk)
        assert stored.contact_information == "*"
        assert stored.citizen.name == "*"

    def test_committee_sees_name_and_contact_in_its_list(self):
        response = self._get(self.committee, reverse("issues:list-assigned-issues"))

        item = response.data["results"][0]
        assert item["citizen"]["name"] == "Awa Koné"
        assert item["citizen"]["gender"] == "female"
        assert item["contact_information"] == "+2290197000000"
        assert item["contact_method"] == PHONE_CHOICE

    def test_reporter_sees_name_and_contact_in_the_detail(self):
        response = self._get(self.reporter, reverse("issues:issue-detail", kwargs={"id": self.issue.id}))

        assert response.data["citizen"]["name"] == "Awa Koné"
        assert response.data["contact_information"] == "+2290197000000"
