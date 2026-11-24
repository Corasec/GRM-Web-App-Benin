from django.urls import reverse

from authentication.factories import UserFactory
from grm.tests.base import DashboardTestCase


class ResetUserPasswordViewTest(DashboardTestCase):
    def setUp(self):
        super().setUp()
        self.manager = UserFactory(grm_manager=True)
        self.manager.set_password("Manager-2026")
        self.manager.save()
        self.target = UserFactory()
        self.target.set_password("Old-pass-2026")
        self.target.save()
        self.url = reverse("dashboard:user_management:reset_password", kwargs={"pk": self.target.id})

    def data(self, **overrides):
        return {
            "new_password": "Nouveau2026",
            "confirm_password": "Nouveau2026",
            "manager_password": "Manager-2026",
            **overrides,
        }

    def test_manager_resets_the_password(self):
        resp = self.post(self.url, self.data(), user=self.manager)

        assert resp.status_code == 302
        self.target.refresh_from_db()
        assert self.target.check_password("Nouveau2026")

    def test_wrong_manager_password_changes_nothing(self):
        self.post(self.url, self.data(manager_password="wrong"), user=self.manager)

        self.target.refresh_from_db()
        assert self.target.check_password("Old-pass-2026")

    def test_weak_or_mismatched_password_is_refused(self):
        self.post(self.url, self.data(new_password="court", confirm_password="court"), user=self.manager)
        self.post(self.url, self.data(confirm_password="Autre2026x"), user=self.manager)

        self.target.refresh_from_db()
        assert self.target.check_password("Old-pass-2026")

    def test_non_manager_is_refused(self):
        resp = self.post(self.url, self.data(), user=UserFactory())

        assert resp.status_code == 403

    def test_only_a_superuser_resets_a_superuser(self):
        admin = UserFactory(is_superuser=True)
        url = reverse("dashboard:user_management:reset_password", kwargs={"pk": admin.id})

        resp = self.post(url, self.data(), user=self.manager)

        assert resp.status_code == 403
        admin.refresh_from_db()
        assert not admin.check_password("Nouveau2026")

    def test_profile_page_offers_the_reset(self):
        resp = self.get(reverse("dashboard:user_management:detail", kwargs={"pk": self.target.id}), user=self.manager)

        assert resp.status_code == 200
        assert b"resetPasswordModal" in resp.content
