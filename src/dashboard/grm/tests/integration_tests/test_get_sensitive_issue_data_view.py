from django.urls import reverse

from authentication.factories import UserFactory
from authentication.models import GovernmentWorker
from grm.tests.base import DashboardTestCase
from issues.factories import (
    AdministrativeRegionFactory,
    CitizenFactory,
    IssueCategoryFactory,
    IssueDepartmentAdministrativeLevelFactory,
    IssueDepartmentFactory,
    IssueFactory,
)


class GetSensitiveIssueDataViewTest(DashboardTestCase):
    """
    Revealing the complainant's name and contact on the dashboard (COSO rules):
    - the national committee account (on any issue) and superusers, with their password;
    - nobody else, not even the committee handling the issue (it sees them in the mobile app).
    """

    def setUp(self):
        super().setUp()
        self.region = AdministrativeRegionFactory(parent=self.root_region)
        self.department = IssueDepartmentFactory()
        self.dep_level = IssueDepartmentAdministrativeLevelFactory(department=self.department)
        self.category = IssueCategoryFactory(assigned_department=self.dep_level)
        citizen = CitizenFactory(name="Awa Koné")
        self.issue = IssueFactory(
            confirmed=True,
            administrative_region=self.region,
            category=self.category,
            citizen=citizen,
            contact_information="+2290197000000",
        )
        # Name and contact are stored encrypted, the issue keeps "*"
        self.issue.anonymize_issue_data()
        self.issue.save()
        self.url = reverse("dashboard:grm:get_sensitive_issue_data")

    def _committee(self, region, password="pwd123"):
        user = UserFactory()
        user.set_password(password)
        user.save()
        GovernmentWorker.objects.create(user=user, department=IssueDepartmentFactory(), administrative_region=region)
        return user

    def test_national_committee_reveals_name_and_contact_with_password(self):
        national = self._committee(self.root_region)

        resp = self.post(self.url, data={"password": "pwd123", "id": self.issue.id}, ajax=True, user=national)

        assert resp.status_code == 200
        assert resp.json()["data"] == {"citizen": "Awa Koné", "contact": "+2290197000000"}

    def test_superuser_reveals_name_and_contact(self):
        admin = UserFactory(is_superuser=True, is_staff=True)
        admin.set_password("adminpwd")
        admin.save()

        resp = self.post(self.url, data={"password": "adminpwd", "id": self.issue.id}, ajax=True, user=admin)

        assert resp.status_code == 200
        assert resp.json()["data"]["citizen"] == "Awa Koné"

    def test_wrong_password_reveals_nothing(self):
        national = self._committee(self.root_region)

        resp = self.post(self.url, data={"password": "wrong", "id": self.issue.id}, ajax=True, user=national)

        assert resp.status_code == 200
        assert resp.json()["data"] is None
        assert "msg" in resp.json()

    def test_local_committee_cannot_reveal_on_the_dashboard_even_when_assigned(self):
        local = self._committee(self.region)
        self.issue.assignee = local
        self.issue.save()

        resp = self.post(self.url, data={"password": "pwd123", "id": self.issue.id}, ajax=True, user=local)

        assert resp.status_code == 403

    def test_grm_manager_cannot_reveal(self):
        manager = UserFactory(grm_manager=True)

        resp = self.post(self.url, data={"password": "irrelevant", "id": self.issue.id}, ajax=True, user=manager)

        assert resp.status_code == 403
