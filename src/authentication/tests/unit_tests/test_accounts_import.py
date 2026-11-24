import io
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from openpyxl import Workbook

from authentication.factories import UserFactory
from authentication.importer import AccountsImportError, import_accounts
from authentication.models import Facilitator, GovernmentWorker, User
from wizard.importer import import_configuration
from wizard.tests.unit_tests.test_configuration_import import build_workbook as build_configuration

PASSWORD = "Mgp2026init"


def build_accounts(**overrides):
    sheets = {
        "Comités": [
            ["Comité", "Niveau", "Région (chemin)", "Prénom", "Nom", "Email"],
            ["Comité national", "Pays", "Bénin", "Comité", "national", "cnational@mgp.bj"],
            ["CLGP", "Commune", "Bénin > BANIKOARA", "CLGP", "BANIKOARA", "clgp.banikoara@mgp.bj"],
            ["CCGP", "Village/Quartier", "Bénin > BANIKOARA > FOUNOUGO", "CCGP", "FOUNOUGO", "ccgp.founougo@mgp.bj"],
        ],
        "Facilitateurs": [
            ["Rôle", "Nom", "Prénom(s)", "Email", "Téléphone", "Région de rattachement (chemin)"],
            [
                "Facilitateur communautaire (FC)",
                "MAMA GAO",
                "Moudachirou",
                "fc.moudachirou.mama-gao@mgp.bj",
                "0197000000",
                "Bénin > BANIKOARA",
            ],
            ["SC", "ADAMOU", "Soumanou", "sc.soumanou.adamou@mgp.bj", "", "Bénin > BANIKOARA"],
        ],
        "Villages couverts": [
            ["Email", "Chemin du village"],
            ["fc.moudachirou.mama-gao@mgp.bj", "Bénin > BANIKOARA > FOUNOUGO"],
            ["fc.moudachirou.mama-gao@mgp.bj", "Bénin > BANIKOARA > GOMPAROU"],
            ["sc.soumanou.adamou@mgp.bj", "Bénin > BANIKOARA > GOMPAROU"],
        ],
    }
    sheets.update(overrides)
    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        if rows is None:
            continue
        ws = wb.create_sheet(title)
        for row in rows:
            ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


@pytest.mark.django_db
class AccountsImportTest(TestCase):
    def setUp(self):
        import_configuration(build_configuration())

    def test_creates_committee_and_field_staff_accounts(self):
        report = import_accounts(build_accounts(), PASSWORD)

        assert report.counts == {"comptes comité": 3, "comptes facilitateur": 2}
        ccgp = User.objects.get(email="ccgp.founougo@mgp.bj")
        assert ccgp.username == "ccgp.founougo@mgp.bj"
        assert ccgp.check_password(PASSWORD)
        assert ccgp.governmentworker.department.name == "CCGP"
        assert ccgp.governmentworker.administrative_region.name == "FOUNOUGO"
        assert GovernmentWorker.objects.get(user__email="cnational@mgp.bj").administrative_region.parent is None

        fc = Facilitator.objects.get(user__email="fc.moudachirou.mama-gao@mgp.bj")
        assert fc.role == "FC"
        assert fc.user.first_name == "Moudachirou" and fc.user.last_name == "MAMA GAO"
        assert sorted(fc.villages.values_list("name", flat=True)) == ["FOUNOUGO", "GOMPAROU"]
        assert Facilitator.objects.get(user__email="sc.soumanou.adamou@mgp.bj").role == "SC"

    def test_weak_password_is_refused(self):
        with pytest.raises(AccountsImportError):
            import_accounts(build_accounts(), "short")
        assert not GovernmentWorker.objects.exists()

    def test_invalid_rows_write_nothing(self):
        committees = [
            ["Comité", "Région (chemin)", "Nom", "Email"],
            ["CCGP", "Bénin > BANIKOARA > FOUNOUGO", "FOUNOUGO", "ccgp.founougo@mgp.bj"],
            ["CCGP", "Bénin > NULLE PART", "X", "ccgp.x@mgp.bj"],
        ]

        with pytest.raises(AccountsImportError) as error:
            import_accounts(build_accounts(**{"Comités": committees}), PASSWORD)

        assert any("région introuvable" in e for e in error.value.errors)
        assert not User.objects.filter(email__endswith="@mgp.bj").exists()

    def test_one_account_per_committee(self):
        committees = [
            ["Comité", "Région (chemin)", "Nom", "Email"],
            ["CCGP", "Bénin > BANIKOARA > FOUNOUGO", "FOUNOUGO", "ccgp.founougo@mgp.bj"],
            ["CCGP", "Bénin > BANIKOARA > FOUNOUGO", "FOUNOUGO", "ccgp.founougo.2@mgp.bj"],
        ]

        with pytest.raises(AccountsImportError) as error:
            import_accounts(build_accounts(**{"Comités": committees}), PASSWORD)

        assert any("un seul compte par comité" in e for e in error.value.errors)

    def test_existing_email_is_skipped(self):
        UserFactory(email="cnational@mgp.bj", username="cnational@mgp.bj")

        report = import_accounts(build_accounts(), PASSWORD)

        assert report.counts["comptes comité"] == 2
        assert any("cnational@mgp.bj" in line for line in report.skipped)

    def test_management_command_prompts_for_the_password(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".xlsx") as tmp:
            tmp.write(build_accounts().read())
            tmp.flush()
            with patch("authentication.management.commands.import_accounts.getpass", side_effect=[PASSWORD, PASSWORD]):
                call_command("import_accounts", tmp.name)
        assert User.objects.filter(email__endswith="@mgp.bj").count() == 5

    def test_management_command_refuses_different_confirmation(self):
        with patch("authentication.management.commands.import_accounts.getpass", side_effect=[PASSWORD, "other1234"]):
            with pytest.raises(CommandError):
                call_command("import_accounts", "/whatever.xlsx")
