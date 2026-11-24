import pytest
from django.test import override_settings
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.reverse import reverse
from rest_framework.test import APITestCase

from authentication.factories import UserFactory


@pytest.mark.django_db
@override_settings(LANGUAGE_CODE='en-us')
class ChangePasswordAPIViewTest(APITestCase):
    def setUp(self):
        self.url = reverse("authentication:change-password")
        self.user = UserFactory()
        self.user.set_password("Initial2026")
        self.user.save()
        self.token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def post(self, current, new):
        return self.client.post(self.url, {"current_password": current, "new_password": new}, format="json")

    def test_changes_the_password_and_keeps_the_token(self):
        response = self.post("Initial2026", "MonVillage7")

        assert response.status_code == status.HTTP_200_OK
        self.user.refresh_from_db()
        assert self.user.check_password("MonVillage7")
        assert Token.objects.get(user=self.user).key == self.token.key

    def test_wrong_current_password(self):
        response = self.post("wrong", "MonVillage7")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "current password" in response.data["error"]
        self.user.refresh_from_db()
        assert self.user.check_password("Initial2026")

    def test_new_password_must_follow_the_rule(self):
        for weak in ["court1", "sanschiffres", "12345678", ""]:
            response = self.post("Initial2026", weak)
            assert response.status_code == status.HTTP_400_BAD_REQUEST, weak
        self.user.refresh_from_db()
        assert self.user.check_password("Initial2026")

    def test_new_password_must_differ(self):
        response = self.post("Initial2026", "Initial2026")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "different" in response.data["error"]

    def test_requires_authentication(self):
        self.client.credentials()

        response = self.post("Initial2026", "MonVillage7")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
