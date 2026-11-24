from django.urls import reverse

from authentication.factories import UserFactory
from grm.constants import ANONYMOUS_CHOICE, LOW_CHOICE
from grm.tests.base import DashboardTestCase
from issues.factories import IssueFactory
from issues.models import (
    AdministrativeRegion,
    IssueCategory,
    IssueDepartmentAdministrativeLevel,
    IssueSubType,
    IssueType,
)
from wizard.constants import COMPLETED_CHOICE
from wizard.importer import import_configuration
from wizard.models import WizardSection
from wizard.tests.unit_tests.test_configuration_import import build_workbook


def url(name, *args):
    return reverse(f"dashboard:grm_configuration:{name}", args=args)


class GrmConfigurationViewsTest(DashboardTestCase):
    def setUp(self):
        super().setUp()
        import_configuration(build_workbook())
        WizardSection.objects.update(status=COMPLETED_CHOICE)
        self.owner = UserFactory(grm_owner=True)
        self.plainte = IssueType.objects.get(name="Plainte")
        self.autre = IssueSubType.objects.get(name="Autre", parent=self.plainte)
        self.ccgp = IssueDepartmentAdministrativeLevel.objects.get(department__name="CCGP")

    def issue(self, category):
        village = AdministrativeRegion.objects.filter(children=None).first()
        return IssueFactory(
            category=category, issue_type=self.plainte, issue_sub_type=self.autre, administrative_region=village
        )

    def test_only_owner_and_superuser(self):
        assert self.get(url("home"), user=UserFactory(grm_manager=True)).status_code == 403
        assert self.get(url("home"), user=self.owner).status_code == 200
        assert self.get(url("home"), user=UserFactory(is_superuser=True)).status_code == 200

    def test_home_shows_the_tree_and_the_wizard_configuration(self):
        resp = self.get(url("home"), user=self.owner)

        content = resp.content.decode()
        assert "Autre plainte" in content and "Dénonciation" in content
        assert "Comité national" in content  # committees from the wizard summary

    def test_add_a_type_a_subtype_and_a_category(self):
        self.post(url("type_create"), {"name": "Suggestion"}, user=self.owner)
        suggestion = IssueType.objects.get(name="Suggestion")
        self.post(url("subtype_create"), {"parent": suggestion.pk, "name": "Amélioration"}, user=self.owner)
        subtype = IssueSubType.objects.get(name="Amélioration")

        resp = self.post(
            url("category_create"),
            {"parent": subtype.pk, "name": "Idée de projet", "assigned_department": self.ccgp.pk, "sensitive": "on"},
            user=self.owner,
        )

        assert resp.status_code == 302
        category = IssueCategory.objects.get(name="Idée de projet")
        assert category.parent == subtype
        assert category.assigned_department == self.ccgp
        assert category.assigned_escalation_department == self.ccgp
        assert category.assigned_appeal_department.department.name == "Comité national"
        assert category.confidentiality_level == ANONYMOUS_CHOICE
        assert category.abbreviation

    def test_category_names_stay_unique(self):
        resp = self.post(
            url("category_create"),
            {"parent": self.autre.pk, "name": "Autre plainte", "assigned_department": self.ccgp.pk},
            user=self.owner,
        )

        assert resp.status_code == 200  # form redisplayed with the error
        assert IssueCategory.objects.filter(name="Autre plainte").count() == 1

    def test_edit_a_used_category_but_not_its_subtype(self):
        category = IssueCategory.objects.get(name="Autre plainte")
        self.issue(category)
        other_subtype = IssueSubType.objects.exclude(pk=self.autre.pk).first()

        self.post(
            url("category_update", category.pk),
            {"parent": other_subtype.pk, "name": "Autre plainte (préciser)", "assigned_department": self.ccgp.pk},
            user=self.owner,
        )

        category.refresh_from_db()
        assert category.name == "Autre plainte (préciser)"
        assert category.parent == self.autre  # parent cannot be changed
        assert category.confidentiality_level == LOW_CHOICE

    def test_used_items_cannot_be_deleted(self):
        category = IssueCategory.objects.get(name="Autre plainte")
        issue = self.issue(category)

        for kind, obj in [("category", category), ("subtype", self.autre), ("type", self.plainte)]:
            self.post(url("delete", kind, obj.pk), {}, user=self.owner)

        assert IssueCategory.objects.filter(pk=category.pk).exists()
        assert IssueType.objects.filter(pk=self.plainte.pk).exists()
        assert issue.__class__.objects.filter(pk=issue.pk).exists()

    def test_parent_with_children_cannot_be_deleted(self):
        self.post(url("delete", "subtype", self.autre.pk), {}, user=self.owner)

        assert IssueSubType.objects.filter(pk=self.autre.pk).exists()

    def test_unused_empty_items_can_be_deleted(self):
        category = IssueCategory.objects.get(name="Autre plainte")

        self.post(url("delete", "category", category.pk), {}, user=self.owner)
        self.post(url("delete", "subtype", self.autre.pk), {}, user=self.owner)

        assert not IssueCategory.objects.filter(pk=category.pk).exists()
        assert not IssueSubType.objects.filter(pk=self.autre.pk).exists()

    def test_sidebar_link_only_for_owner(self):
        assert url("home") in self.get(reverse("dashboard:diagnostics:home"), user=self.owner).content.decode()
        manager_page = self.get(reverse("dashboard:diagnostics:home"), user=UserFactory(grm_manager=True))
        assert url("home") not in manager_page.content.decode()
