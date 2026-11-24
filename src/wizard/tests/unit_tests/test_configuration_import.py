import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from openpyxl import Workbook

from grm.constants import ANONYMOUS_CHOICE, LOW_CHOICE
from issues.factories import IssueFactory
from issues.models import (
    AdministrativeLevel,
    AdministrativeRegion,
    CitizenAgeGroup,
    Component,
    IssueCategory,
    IssueDepartment,
    IssueStatus,
    IssueSubType,
    IssueType,
    SubComponent,
)
from wizard.constants import COMPLETED_CHOICE, IN_PROGRESS_CHOICE, SUMMARY_CHOICE
from wizard.importer import ConfigurationImportError, import_configuration
from wizard.models import WizardSection


def build_workbook(**overrides):
    sheets = {
        "Projet": [["Nom", "Description"], ["COSO", "Projet COSO Bénin"]],
        "Niveaux": [["Niveau"], ["Pays"], ["Commune"], ["Village/Quartier"]],
        "Hiérarchie": [
            ["Pays", "Commune", "Village/Quartier"],
            ["Bénin", "BANIKOARA", "FOUNOUGO"],
            ["Bénin", "BANIKOARA", "GOMPAROU"],
            ["Bénin", "MALANVILLE", "GUÉNÉ  CENTRE"],  # double space: normalised
        ],
        "Comités": [
            ["Comité", "Niveau", "Délai (jours ouvrables)"],
            ["CCGP", "Village/Quartier", 3],
            ["CLGP", "Commune", 3],
            ["Comité national", "Pays", 5],
        ],
        "Catégories": [
            [
                "Type",
                "Sous-type",
                "Catégorie",
                "Niveau d'affectation",
                "Comité",
                "Délai spécifique (jours ouvrables)",
                "Confidentialité",
            ],
            [
                "Plainte",
                "Type 3 — Travaux et prestations",
                "Paiement des contrats formels",
                "Lieu",
                "CCGP",
                None,
                "Normale",
            ],
            ["Plainte", "Autre", "Autre plainte", "Lieu", "CCGP", None, "Normale"],
            [
                "Dénonciation",
                "Type 4 — Violation du code de conduite",
                "Type 4.2 — VBG / EAS / HS",
                "Pays",
                "Comité national",
                22,
                "Sensible",
            ],
            [
                "Dénonciation",
                "Type 4 — Violation du code de conduite",
                "Type 4.4 — Non-respect des us et coutumes",
                "Commune",
                "CLGP",
                None,
                "Sensible",
            ],
        ],
        "Tranches d'âge": [["Tranche d'âge"], ["0 – 14 ans"], ["15 – 29 ans"]],
        "Composantes": [
            ["Composante", "Description", "Sous-composante"],
            ["Composante 1", "Investir", None],
            ["Composante 2", "Renforcer", None],
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
class ConfigurationImportTest(TestCase):
    def test_imports_the_whole_configuration(self):
        report = import_configuration(build_workbook())

        assert list(AdministrativeLevel.objects.order_by("id").values_list("name", flat=True)) == [
            "Pays",
            "Commune",
            "Village/Quartier",
        ]
        assert AdministrativeRegion.objects.count() == 6  # Bénin + 2 communes + 3 villages
        assert AdministrativeRegion.objects.filter(name="GUÉNÉ CENTRE").exists()
        assert dict(IssueDepartment.objects.values_list("name", "processing_days")) == {
            "CCGP": 3,
            "CLGP": 3,
            "Comité national": 5,
        }

        vbg = IssueCategory.objects.get(name="Type 4.2 — VBG / EAS / HS")
        assert vbg.assigned_department.department.name == "Comité national"
        assert vbg.assigned_department.administrative_level.name == "Pays"
        assert vbg.processing_days == 22
        assert vbg.confidentiality_level == ANONYMOUS_CHOICE
        assert IssueCategory.objects.get(name="Paiement des contrats formels").confidentiality_level == LOW_CHOICE
        assert vbg.parent.parent.name == "Dénonciation"
        assert IssueType.objects.count() == 2
        assert IssueSubType.objects.filter(name="Autre", parent__name="Plainte").exists()
        assert report.counts["catégories"] == 4

        assert IssueStatus.objects.filter(initial_status=True).exists()
        assert IssueStatus.objects.filter(final_status=True).exists()
        assert CitizenAgeGroup.objects.count() == 2
        assert Component.objects.count() == 2 and not SubComponent.objects.exists()  # subcomponents optional

        statuses = dict(WizardSection.objects.values_list("name", "status"))
        for name, status in statuses.items():
            assert status == (IN_PROGRESS_CHOICE if name == SUMMARY_CHOICE else COMPLETED_CHOICE)

    def test_invalid_workbook_writes_nothing(self):
        bad_categories = [
            ["Type", "Sous-type", "Catégorie", "Comité"],
            ["Plainte", "Type 3", "Paiement", "Comité inconnu"],
        ]

        with pytest.raises(ConfigurationImportError) as error:
            import_configuration(build_workbook(**{"Catégories": bad_categories}))

        assert any("comité inconnu" in e for e in error.value.errors)
        assert not AdministrativeLevel.objects.exists()
        assert not IssueCategory.objects.exists()

    def test_hierarchy_columns_must_match_the_levels(self):
        with pytest.raises(ConfigurationImportError) as error:
            import_configuration(build_workbook(**{"Hiérarchie": [["Pays", "Village"], ["Bénin", "X"]]}))

        assert any("Hiérarchie" in e for e in error.value.errors)

    def test_missing_sheet_is_reported(self):
        with pytest.raises(ConfigurationImportError) as error:
            import_configuration(build_workbook(**{"Comités": None}))

        assert any("Comités" in e for e in error.value.errors)

    def test_refused_once_issues_exist(self):
        IssueFactory()

        with pytest.raises(ConfigurationImportError) as error:
            import_configuration(build_workbook())

        assert any("plaintes existent" in e for e in error.value.errors)

    def test_management_command(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".xlsx") as tmp:
            tmp.write(build_workbook().read())
            tmp.flush()
            call_command("import_configuration", tmp.name)
        assert IssueCategory.objects.count() == 4

    def test_management_command_reports_errors(self):
        with pytest.raises(CommandError):
            call_command("import_configuration", "/nonexistent.xlsx")


@pytest.mark.django_db
class ConfigurationImportViewTest(TestCase):
    """Import button of the wizard (GRM owner, wizard not finished)."""

    def setUp(self):
        from authentication.factories import UserFactory

        WizardSection.objects.update(status=IN_PROGRESS_CHOICE)
        self.owner = UserFactory(grm_owner=True)
        self.url = "/wizard/import-configuration/"

    def _post(self, user, upload=None):
        upload = upload or build_workbook()
        upload.name = "configuration.xlsx"
        self.client.force_login(user)
        return self.client.post(self.url, {"configuration_file": upload})

    def test_owner_imports_and_lands_on_the_summary(self):
        response = self._post(self.owner)

        assert response.status_code == 302
        assert "step=" in response.url
        assert IssueCategory.objects.count() == 4

    def test_errors_write_nothing(self):
        bad = build_workbook(**{"Comités": None})

        response = self._post(self.owner, bad)

        assert response.status_code == 302
        assert not IssueCategory.objects.exists()
