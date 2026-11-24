import pytest
from django.db import IntegrityError
from django.test import TestCase

from authentication.factories import FacilitatorFactory, GovernmentWorkerFactory, UserFactory
from authentication.models import User
from grm.utils import reset_sequences
from issues.factories import (
    AdministrativeLevelFactory,
    AdministrativeRegionFactory,
    IssueCategoryFactory,
    IssueDepartmentAdministrativeLevelFactory,
    IssueDepartmentFactory,
    IssueFactory,
)


@pytest.mark.django_db
class IssueGetAssigneeTest(TestCase):
    """
    Routing rules (COSO MGP, Benin):
      tree: pays > département > commune > arrondissement > village
      committees: CCGP (village), CLGP (commune), national committee (pays)
      non-sensitive issue -> CCGP of the village; sensitive issue -> national committee;
      failsafe: climb to the next committee level, skipping arrondissement and département.
    """

    def setUp(self):
        reset_sequences()
        # Administrative levels
        self.lvl_country = AdministrativeLevelFactory(name="pays")
        self.lvl_department = AdministrativeLevelFactory(name="departement")
        self.lvl_commune = AdministrativeLevelFactory(name="commune")
        self.lvl_arrondissement = AdministrativeLevelFactory(name="arrondissement")
        self.lvl_village = AdministrativeLevelFactory(name="village")

        # Regions
        self.country = AdministrativeRegionFactory(name="Bénin", administrative_level=self.lvl_country, parent=None)
        self.department = AdministrativeRegionFactory(
            name="Alibori", administrative_level=self.lvl_department, parent=self.country
        )
        self.commune = AdministrativeRegionFactory(
            name="Malanville", administrative_level=self.lvl_commune, parent=self.department
        )
        self.arrondissement = AdministrativeRegionFactory(
            name="Guéné", administrative_level=self.lvl_arrondissement, parent=self.commune
        )
        self.village = AdministrativeRegionFactory(
            name="Village A", administrative_level=self.lvl_village, parent=self.arrondissement
        )
        self.other_village = AdministrativeRegionFactory(
            name="Village B", administrative_level=self.lvl_village, parent=self.arrondissement
        )

        # Committees (departments attached to their level, as configured in the wizard)
        self.ccgp = IssueDepartmentFactory(name="CCGP")
        self.clgp = IssueDepartmentFactory(name="CLGP")
        self.national = IssueDepartmentFactory(name="Comité national")
        self.ccgp_at_village = IssueDepartmentAdministrativeLevelFactory(
            department=self.ccgp, administrative_level=self.lvl_village
        )
        self.clgp_at_commune = IssueDepartmentAdministrativeLevelFactory(
            department=self.clgp, administrative_level=self.lvl_commune
        )
        self.national_at_country = IssueDepartmentAdministrativeLevelFactory(
            department=self.national, administrative_level=self.lvl_country
        )

        # Categories
        self.normal_category = IssueCategoryFactory(assigned_department=self.ccgp_at_village)
        self.sensitive_category = IssueCategoryFactory(assigned_department=self.national_at_country)
        self.commune_category = IssueCategoryFactory(assigned_department=self.clgp_at_commune)

    def _committee(self, department, region):
        return GovernmentWorkerFactory(department=department, administrative_region=region).user

    def _issue(self, category, region=None):
        return IssueFactory(category=category, administrative_region=region or self.village, assignee=None)

    def test_normal_issue_goes_to_village_committee(self):
        ccgp = self._committee(self.ccgp, self.village)
        self._committee(self.clgp, self.commune)
        self._committee(self.national, self.country)

        assignee = self._issue(self.normal_category).get_assignee()

        self.assertEqual(assignee, ccgp)
        self.assertIsInstance(assignee, User)

    def test_normal_issue_does_not_go_to_another_village_committee(self):
        self._committee(self.ccgp, self.other_village)
        clgp = self._committee(self.clgp, self.commune)

        self.assertEqual(self._issue(self.normal_category).get_assignee(), clgp)

    def test_sensitive_issue_goes_to_national_committee(self):
        self._committee(self.ccgp, self.village)
        self._committee(self.clgp, self.commune)
        national = self._committee(self.national, self.country)

        self.assertEqual(self._issue(self.sensitive_category).get_assignee(), national)

    def test_sensitive_issue_never_falls_back_down_to_local_committees(self):
        self._committee(self.ccgp, self.village)
        self._committee(self.clgp, self.commune)

        self.assertIsNone(self._issue(self.sensitive_category).get_assignee())

    def test_commune_level_category_goes_to_commune_committee(self):
        self._committee(self.ccgp, self.village)
        clgp = self._committee(self.clgp, self.commune)

        self.assertEqual(self._issue(self.commune_category).get_assignee(), clgp)

    def test_failsafe_village_without_committee_goes_to_commune_committee(self):
        clgp = self._committee(self.clgp, self.commune)
        self._committee(self.national, self.country)

        self.assertEqual(self._issue(self.normal_category).get_assignee(), clgp)

    def test_failsafe_skips_arrondissement_and_departement(self):
        """Accounts placed on levels without a committee must never receive issues."""
        GovernmentWorkerFactory(department=self.ccgp, administrative_region=self.arrondissement)
        GovernmentWorkerFactory(department=self.clgp, administrative_region=self.department)
        national = self._committee(self.national, self.country)

        self.assertEqual(self._issue(self.normal_category).get_assignee(), national)

    def test_failsafe_ignores_non_committee_department_on_committee_level(self):
        """At commune level only departments attached to that level (CLGP) count."""
        GovernmentWorkerFactory(department=self.ccgp, administrative_region=self.commune)
        national = self._committee(self.national, self.country)

        self.assertEqual(self._issue(self.normal_category).get_assignee(), national)

    def test_issue_reported_above_target_level_uses_issue_region(self):
        """An issue located at commune level for a village-level category goes to the CLGP."""
        clgp = self._committee(self.clgp, self.commune)

        self.assertEqual(self._issue(self.normal_category, region=self.commune).get_assignee(), clgp)

    def test_no_committee_account_at_all_returns_none(self):
        self.assertIsNone(self._issue(self.normal_category).get_assignee())

    def test_facilitators_never_receive_issues(self):
        """Field facilitators (even with the legacy village_secretary flag) create and follow issues only."""
        FacilitatorFactory(administrative_region=self.village, village_secretary=True)
        ccgp = self._committee(self.ccgp, self.village)

        self.assertEqual(self._issue(self.normal_category).get_assignee(), ccgp)

    def test_only_one_committee_account_per_department_and_region(self):
        self._committee(self.ccgp, self.village)

        with self.assertRaises(IntegrityError):
            GovernmentWorkerFactory(department=self.ccgp, administrative_region=self.village, user=UserFactory())


@pytest.mark.django_db
class AdministrativeRegionAncestorAtLevelTest(TestCase):
    def setUp(self):
        reset_sequences()
        self.lvl_country = AdministrativeLevelFactory()
        self.lvl_commune = AdministrativeLevelFactory()
        self.lvl_village = AdministrativeLevelFactory()
        self.country = AdministrativeRegionFactory(administrative_level=self.lvl_country, parent=None)
        self.commune = AdministrativeRegionFactory(administrative_level=self.lvl_commune, parent=self.country)
        self.village = AdministrativeRegionFactory(administrative_level=self.lvl_village, parent=self.commune)

    def test_returns_self_when_at_level(self):
        self.assertEqual(self.village.get_ancestor_at_level(self.lvl_village.id), self.village)

    def test_returns_ancestor_at_level(self):
        self.assertEqual(self.village.get_ancestor_at_level(self.lvl_commune.id), self.commune)
        self.assertEqual(self.village.get_ancestor_at_level(self.lvl_country.id), self.country)

    def test_returns_none_when_region_is_above_level(self):
        self.assertIsNone(self.commune.get_ancestor_at_level(self.lvl_village.id))
