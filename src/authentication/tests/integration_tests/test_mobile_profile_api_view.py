import pytest
from django.test import override_settings
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.reverse import reverse
from rest_framework.test import APITestCase

from authentication.constants import MOBILE_ACCOUNT_NOT_ALLOWED_ERROR_MESSAGE
from authentication.factories import FacilitatorFactory, GovernmentWorkerFactory, UserFactory
from grm.utils import reset_sequences
from issues.factories import AdministrativeLevelFactory, AdministrativeRegionFactory, IssueDepartmentFactory


@pytest.mark.django_db
@override_settings(LANGUAGE_CODE='en-us')
class MobileProfileAPIViewTest(APITestCase):
    """
    Profile used by the mobile app: account type, committee and the locations
    offered by the issue "location" step.
    Benin tree: pays > departement > commune > arrondissement > village.
    """

    def setUp(self):
        reset_sequences()
        self.url = reverse("authentication:mobile-profile")

        lvl = {
            name: AdministrativeLevelFactory(name=name)
            for name in ["pays", "departement", "commune", "arrondissement", "village"]
        }
        self.country = AdministrativeRegionFactory(name="Bénin", administrative_level=lvl["pays"], parent=None)
        self.departement = AdministrativeRegionFactory(
            name="Alibori", administrative_level=lvl["departement"], parent=self.country
        )
        self.commune = AdministrativeRegionFactory(
            name="Malanville", administrative_level=lvl["commune"], parent=self.departement
        )
        self.arr_1 = AdministrativeRegionFactory(
            name="Guéné", administrative_level=lvl["arrondissement"], parent=self.commune
        )
        self.arr_2 = AdministrativeRegionFactory(
            name="Garou", administrative_level=lvl["arrondissement"], parent=self.commune
        )
        self.village_1 = AdministrativeRegionFactory(name="V1", administrative_level=lvl["village"], parent=self.arr_1)
        self.village_2 = AdministrativeRegionFactory(name="V2", administrative_level=lvl["village"], parent=self.arr_1)
        self.village_3 = AdministrativeRegionFactory(name="V3", administrative_level=lvl["village"], parent=self.arr_2)

    def _get(self, user):
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return self.client.get(self.url)

    def _committee(self, name, region):
        return GovernmentWorkerFactory(department=IssueDepartmentFactory(name=name), administrative_region=region).user

    @staticmethod
    def _location_ids(response):
        return [r["id"] for r in response.data["location"]["regions"]]

    def test_requires_authentication(self):
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_account_neither_committee_nor_facilitator_is_refused(self):
        response = self._get(UserFactory(grm_manager=True))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.data["error"] == MOBILE_ACCOUNT_NOT_ALLOWED_ERROR_MESSAGE

    def test_village_committee_location_is_fixed_to_its_village(self):
        response = self._get(self._committee("CCGP", self.village_1))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["account_type"] == "committee"
        assert response.data["can_process_issues"] is True
        assert response.data["committee"]["department"]["name"] == "CCGP"
        assert response.data["committee"]["administrative_level"]["name"] == "village"
        assert response.data["administrative_region"]["id"] == self.village_1.id
        assert response.data["location"]["mode"] == "fixed"
        assert self._location_ids(response) == [self.village_1.id]

    def test_commune_committee_chooses_commune_or_its_villages(self):
        response = self._get(self._committee("CLGP", self.commune))

        assert response.data["account_type"] == "committee"
        assert response.data["location"]["mode"] == "list"
        ids = self._location_ids(response)
        assert ids[0] == self.commune.id
        assert set(ids[1:]) == {self.village_1.id, self.village_2.id, self.village_3.id}

    def test_national_committee_location_is_free(self):
        response = self._get(self._committee("Comité national", self.country))

        assert response.data["location"] == {"mode": "free", "regions": []}

    def test_facilitator_chooses_among_covered_villages_across_arrondissements(self):
        facilitator = FacilitatorFactory(administrative_region=self.arr_1)
        facilitator.villages.set([self.village_1, self.village_3])

        response = self._get(facilitator.user)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["account_type"] == "facilitator"
        assert response.data["can_process_issues"] is False
        assert response.data["committee"] is None
        assert response.data["location"]["mode"] == "list"
        assert set(self._location_ids(response)) == {self.village_1.id, self.village_3.id}

    def test_facilitator_without_covered_villages_uses_villages_of_its_region(self):
        facilitator = FacilitatorFactory(administrative_region=self.arr_1)

        response = self._get(facilitator.user)

        assert response.data["location"]["mode"] == "list"
        assert set(self._location_ids(response)) == {self.village_1.id, self.village_2.id}

    def test_facilitator_with_a_single_village_is_fixed(self):
        facilitator = FacilitatorFactory(administrative_region=self.arr_2)
        facilitator.villages.set([self.village_3])

        response = self._get(facilitator.user)

        assert response.data["location"]["mode"] == "fixed"
        assert self._location_ids(response) == [self.village_3.id]

    def test_user_fields_are_returned(self):
        user = UserFactory(first_name="Awa", last_name="Koné", phone_number="+22990000000")
        FacilitatorFactory(user=user, administrative_region=self.arr_1)

        response = self._get(user)

        assert response.data["user"]["id"] == user.id
        assert response.data["user"]["name"] == user.name
        assert response.data["user"]["phone"] == "+22990000000"
        assert response.data["user"]["photo"] is None

    def test_field_role_is_returned_for_field_staff(self):
        facilitator = FacilitatorFactory(administrative_region=self.arr_1, role="SC")

        response = self._get(facilitator.user)

        assert response.data["field_role"] == "SC"

    def test_committee_has_no_field_role(self):
        response = self._get(self._committee("CCGP", self.village_1))

        assert response.data["field_role"] == ""
