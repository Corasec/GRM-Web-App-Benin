from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from authentication.models import User

COMMAND = "authentication.management.commands.create_grm_owner"


@pytest.mark.django_db
class CreateGrmOwnerTest(TestCase):
    def test_creates_the_installation_administrator(self):
        with patch(f"{COMMAND}.getpass", side_effect=["Owner-pass-2026", "Owner-pass-2026"]):
            call_command("create_grm_owner", "--email", "Admin@MGP.bj")

        user = User.objects.get(email="admin@mgp.bj")
        assert user.username == "admin@mgp.bj"
        assert user.grm_owner and user.grm_manager and user.is_staff and user.is_superuser
        assert user.check_password("Owner-pass-2026")

    def test_upgrades_an_existing_user_without_changing_the_password(self):
        user = User.objects.create_user(username="x", email="admin@mgp.bj", password="Old-pass-2026")

        with patch(f"{COMMAND}.input", return_value="n"):
            call_command("create_grm_owner", "--email", "admin@mgp.bj")

        user.refresh_from_db()
        assert user.grm_owner and user.is_superuser
        assert user.check_password("Old-pass-2026")

    def test_password_confirmation_must_match(self):
        with patch(f"{COMMAND}.getpass", side_effect=["Owner-pass-2026", "other"]):
            with pytest.raises(CommandError):
                call_command("create_grm_owner", "--email", "admin@mgp.bj")
        assert not User.objects.filter(email="admin@mgp.bj").exists()
