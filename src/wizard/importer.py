"""
Import the whole wizard configuration from one Excel workbook (see docs/excel-import.md).

Sheets (headers are matched case- and accent-insensitively; extra columns are ignored):

- "Projet":            Nom | Description
- "Niveaux":           Niveau                         (top-down order, e.g. Pays ... Village/Quartier)
- "Hiérarchie":        one column per level, one row per full path (same as wizard step 3)
- "Comités":           Comité | Niveau | Délai (jours ouvrables)
- "Catégories":        Type | Sous-type | Catégorie | Comité | Délai spécifique | Confidentialité | Abréviation
- "Statuts" (opt.):    Statut (initial / ouvert / rejeté / résolu) | Nom | Seuil (jours)
- "Tranches d'âge":    Tranche d'âge
- "Groupes de citoyens" (opt.): Nom | Type (1 or 2)
- "Composantes":       Composante | Description | Sous-composante (opt.) | Description sous-composante (opt.)
- "Sous-projets" (opt.): Groupe de sous-projets

The workbook is fully read and validated first: on any error nothing is written. The import
replaces the configuration, so it is only allowed on a fresh installation (no issue and no
committee / field staff account yet). Afterwards every wizard section is marked completed except
the summary, which the GRM owner reviews and validates.
"""

import io
import re
import unicodedata
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import transaction
from openpyxl import Workbook, load_workbook

from authentication.models import Facilitator, GovernmentWorker
from dashboard.models import Project
from grm.constants import ANONYMOUS_CHOICE, FEWER_ISSUES_CHOICE, LOW_CHOICE
from issues.models import (
    AdministrativeLevel,
    AdministrativeRegion,
    CitizenAgeGroup,
    CitizenGroup,
    Component,
    Issue,
    IssueCategory,
    IssueDepartment,
    IssueDepartmentAdministrativeLevel,
    IssueStatus,
    IssueSubType,
    IssueType,
    SubComponent,
    SubProjectGroup,
)
from wizard.constants import (
    CITIZEN_GROUP2_CHOICE,
    CITIZEN_GROUP_CHOICE,
    COMPLETED_CHOICE,
    IN_PROGRESS_CHOICE,
    SUMMARY_CHOICE,
)
from wizard.models import WizardSection
from wizard.utils import AdministrativeRegionProcessor


class ConfigurationImportError(Exception):
    def __init__(self, errors):
        super().__init__("\n".join(errors))
        self.errors = errors


def norm(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def clean(value):
    return re.sub(r"\s+", " ", str(value)).strip() if value is not None else ""


STATUS_FLAGS = {
    "initial": "initial_status",
    "ouvert": "open_status",
    "open": "open_status",
    "rejete": "rejected_status",
    "rejected": "rejected_status",
    "resolu": "final_status",
    "resolved": "final_status",
    "final": "final_status",
}
DEFAULT_STATUSES = [
    ("initial_status", "Créé", 3),
    ("open_status", "Ouvert", 5),
    ("rejected_status", "Rejeté", 1),
    ("final_status", "Résolu", 1),
]
SENSITIVE_VALUES = {"sensible", "sensitive", "anonyme", "anonymous", "confidentiel", "confidential", "oui", "yes"}


@dataclass
class ImportReport:
    counts: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


class _Sheet:
    """Rows of a sheet as dicts keyed by normalised header aliases."""

    def __init__(self, ws, columns, errors, name):
        self.name = name
        self.rows = []
        header = [norm(c) for c in next(ws.iter_rows(min_row=1, max_row=1, values_only=True), [])]
        index = {}
        for key, aliases in columns.items():
            for alias in aliases:
                if norm(alias) in header:
                    index[key] = header.index(norm(alias))
                    break
        self.index = index
        for row_number, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not any(c not in (None, "") for c in row):
                continue
            self.rows.append((row_number, {k: clean(row[i]) if i < len(row) else "" for k, i in index.items()}))

    def require(self, keys, errors):
        missing = [k for k in keys if k not in self.index]
        if missing:
            errors.append(f"[{self.name}] colonne(s) manquante(s) : {', '.join(missing)}")
            return False
        return True


def _find_sheet(wb, *names):
    wanted = {norm(n) for n in names}
    for ws in wb.worksheets:
        if norm(ws.title) in wanted:
            return ws
    return None


def read_configuration(file_obj):
    """Read and validate the workbook; return the parsed configuration or raise ConfigurationImportError."""
    errors = []
    try:
        wb = load_workbook(file_obj, data_only=True)
    except Exception:
        raise ConfigurationImportError(["Le fichier n'est pas un classeur Excel (.xlsx) lisible."])

    def sheet(names, columns, required=True, required_columns=()):
        ws = _find_sheet(wb, *names)
        if ws is None:
            if required:
                errors.append(f"Onglet manquant : « {names[0]} »")
            return None
        s = _Sheet(ws, columns, errors, ws.title)
        if not s.require(required_columns, errors):
            return None
        return s

    conf = {}

    # Project
    s = sheet(
        ["Projet", "Project"], {"name": ["Nom", "Name"], "description": ["Description"]}, required_columns=["name"]
    )
    if s:
        if not s.rows or not s.rows[0][1].get("name"):
            errors.append("[Projet] le nom du projet est obligatoire")
        else:
            conf["project"] = s.rows[0][1]

    # Levels
    s = sheet(["Niveaux", "Levels"], {"name": ["Niveau", "Level", "Nom"]}, required_columns=["name"])
    levels = []
    if s:
        levels = [r["name"] for _, r in s.rows if r.get("name")]
        if not levels:
            errors.append("[Niveaux] au moins un niveau administratif est requis")
        dup = {n for n in levels if levels.count(n) > 1}
        if dup:
            errors.append(f"[Niveaux] niveaux en double : {', '.join(sorted(dup))}")
    conf["levels"] = levels

    # Hierarchy (kept as rows; validated against the levels)
    ws = _find_sheet(wb, "Hiérarchie", "Hierarchie", "Hierarchy", "Régions", "Regions")
    if ws is None:
        errors.append("Onglet manquant : « Hiérarchie »")
    else:
        rows = list(ws.iter_rows(values_only=True))
        header = [clean(c) for c in (rows[0] if rows else []) if c not in (None, "")]
        if levels and header != levels:
            errors.append(
                f"[Hiérarchie] les colonnes doivent être exactement les niveaux, dans l'ordre : {' | '.join(levels)}"
            )
        body = [[clean(c) for c in r[: len(header)]] for r in rows[1:] if any(c not in (None, "") for c in r)]
        roots = {r[0] for r in body if r and r[0]}
        if len(roots) > 1:
            errors.append(f"[Hiérarchie] une seule racine est autorisée, trouvé : {', '.join(sorted(roots))}")
        if not body:
            errors.append("[Hiérarchie] aucune ligne")
        conf["hierarchy"] = (header, body)

    # Committees
    s = sheet(
        ["Comités", "Comites", "Committees", "Départements", "Departements"],
        {
            "name": ["Comité", "Comite", "Département", "Departement", "Committee"],
            "level": ["Niveau", "Level"],
            "days": ["Délai (jours ouvrables)", "Délai", "Delai", "Processing days"],
        },
        required_columns=["name", "level"],
    )
    committees = {}
    if s:
        for row, r in s.rows:
            if r["level"] not in levels:
                errors.append(f"[Comités] ligne {row} : niveau inconnu « {r['level']} »")
            days = r.get("days", "")
            if days and not days.isdigit():
                errors.append(f"[Comités] ligne {row} : délai invalide « {days} » (nombre de jours ouvrables)")
            if r["name"] in committees:
                errors.append(f"[Comités] ligne {row} : comité en double « {r['name']} »")
            committees[r["name"]] = {"level": r["level"], "days": int(days) if days.isdigit() else None}
        if not committees:
            errors.append("[Comités] au moins un comité est requis")
    conf["committees"] = committees

    # Categories
    s = sheet(
        ["Catégories", "Categories"],
        {
            "type": ["Type", "Type (Quel signalez-vous ?)"],
            "subtype": ["Sous-type", "Sous-type (Quel type ?)", "Subtype"],
            "category": ["Catégorie", "Catégorie (De quoi s'agit-il ?)", "Category"],
            "committee": ["Comité", "Comite", "Committee"],
            "days": ["Délai spécifique (jours ouvrables)", "Délai spécifique", "Delai specifique"],
            "confidentiality": ["Confidentialité", "Confidentialite", "Confidentiality"],
            "abbreviation": ["Abréviation", "Abreviation", "Abbreviation"],
        },
        required_columns=["type", "subtype", "category", "committee"],
    )
    categories = []
    if s:
        seen = set()
        for row, r in s.rows:
            if not (r["type"] and r["subtype"] and r["category"]):
                errors.append(f"[Catégories] ligne {row} : type, sous-type et catégorie sont obligatoires")
                continue
            if r["committee"] not in committees:
                errors.append(f"[Catégories] ligne {row} : comité inconnu « {r['committee']} » (voir l'onglet Comités)")
            if r["category"] in seen:
                errors.append(
                    f"[Catégories] ligne {row} : catégorie en double « {r['category']} » (les noms doivent être uniques)"
                )
            seen.add(r["category"])
            days = r.get("days", "")
            if days and not days.isdigit():
                errors.append(f"[Catégories] ligne {row} : délai spécifique invalide « {days} »")
            categories.append(
                {
                    **r,
                    "days": int(days) if days.isdigit() else None,
                    "sensitive": norm(r.get("confidentiality")) in SENSITIVE_VALUES,
                }
            )
        if not categories:
            errors.append("[Catégories] au moins une catégorie est requise")
    conf["categories"] = categories

    # Statuses (optional: defaults)
    statuses = {flag: {"name": name, "days": days} for flag, name, days in DEFAULT_STATUSES}
    s = sheet(
        ["Statuts", "Statuses"],
        {"flag": ["Statut", "Status"], "name": ["Nom", "Name"], "days": ["Seuil (jours)", "Seuil", "Threshold"]},
        required=False,
        required_columns=["flag", "name"],
    )
    if s:
        for row, r in s.rows:
            flag = STATUS_FLAGS.get(norm(r["flag"]))
            if not flag:
                errors.append(
                    f"[Statuts] ligne {row} : statut inconnu « {r['flag']} » (initial, ouvert, rejeté, résolu)"
                )
                continue
            days = r.get("days", "")
            statuses[flag] = {
                "name": r["name"],
                "days": int(days) if days.isdigit() and int(days) > 0 else statuses[flag]["days"],
            }
    conf["statuses"] = statuses

    # Age groups
    s = sheet(
        ["Tranches d'âge", "Tranches d age", "Age groups"],
        {"name": ["Tranche d'âge", "Tranche d age", "Age group", "Nom"]},
        required_columns=["name"],
    )
    conf["age_groups"] = [r["name"] for _, r in s.rows if r.get("name")] if s else []
    if s and not conf["age_groups"]:
        errors.append("[Tranches d'âge] au moins une tranche est requise")

    # Citizen groups (optional)
    s = sheet(
        ["Groupes de citoyens", "Citizen groups"],
        {"name": ["Nom", "Name"], "type": ["Type"]},
        required=False,
        required_columns=["name"],
    )
    conf["citizen_groups"] = (
        [(r["name"], "2" if r.get("type") == "2" else "1") for _, r in s.rows if r.get("name")] if s else []
    )

    # Components (subcomponents optional)
    s = sheet(
        ["Composantes", "Components"],
        {
            "name": ["Composante", "Component"],
            "description": ["Description"],
            "sub": ["Sous-composante", "Subcomponent"],
            "sub_description": ["Description sous-composante", "Subcomponent description"],
        },
        required_columns=["name"],
    )
    components = {}
    if s:
        for row, r in s.rows:
            if not r.get("name"):
                continue
            comp = components.setdefault(r["name"], {"description": r.get("description") or r["name"], "subs": []})
            if r.get("sub"):
                comp["subs"].append((r["sub"], r.get("sub_description") or r["sub"]))
        if not components:
            errors.append("[Composantes] au moins une composante est requise")
    conf["components"] = components

    # Subproject groups (optional)
    s = sheet(
        ["Sous-projets", "Sous projets", "Subprojects"],
        {"name": ["Groupe de sous-projets", "Sous-projet", "Nom", "Name"]},
        required=False,
        required_columns=["name"],
    )
    conf["subprojects"] = [r["name"] for _, r in s.rows if r.get("name")] if s else []

    if errors:
        raise ConfigurationImportError(errors)
    return conf


def check_can_import():
    """The import replaces the configuration: only on a fresh installation."""
    errors = []
    if Issue.objects.exists():
        errors.append("Des plaintes existent déjà : la configuration ne peut plus être remplacée par un import.")
    if GovernmentWorker.objects.exists() or Facilitator.objects.exists():
        errors.append(
            "Des comptes comité ou facilitateur existent déjà : importez la configuration avant de créer les comptes."
        )
    if errors:
        raise ConfigurationImportError(errors)


def _abbreviation(index, name):
    letters = "".join(w[0] for w in norm(name).split()[:3]).upper()
    return f"{letters or 'CAT'}{index:02d}"


def import_configuration(file_obj):
    """Validate then import the configuration workbook. Returns an ImportReport."""
    conf = read_configuration(file_obj)
    check_can_import()
    report = ImportReport()

    with transaction.atomic():
        # Replace the existing configuration (fresh installation only, checked above)
        IssueCategory.objects.all().delete()
        IssueSubType.objects.all().delete()
        IssueType.objects.all().delete()
        IssueDepartmentAdministrativeLevel.objects.all().delete()
        IssueDepartment.objects.all().delete()
        SubComponent.objects.all().delete()
        Component.objects.all().delete()
        SubProjectGroup.objects.all().delete()
        CitizenAgeGroup.objects.all().delete()
        CitizenGroup.objects.all().delete()
        AdministrativeRegion.objects.all().delete()
        AdministrativeLevel.objects.all().delete()

        project = Project.objects.first() or Project()
        project.name = conf["project"]["name"]
        project.description = conf["project"].get("description", "")
        project.save()

        level_objects = {name: AdministrativeLevel.objects.create(name=name) for name in conf["levels"]}
        report.counts["niveaux"] = len(level_objects)

        header, body = conf["hierarchy"]
        temp = Workbook()
        temp.active.append(header)
        for row in body:
            temp.active.append(row)
        buffer = io.BytesIO()
        temp.save(buffer)
        buffer.seek(0)
        processor = AdministrativeRegionProcessor()
        try:
            created, duplicates, _ = processor.process_excel(buffer)
        except ValidationError as error:
            raise ConfigurationImportError([f"[Hiérarchie] {m}" for m in error.messages])
        if processor.stats["errors"]:
            raise ConfigurationImportError([f"[Hiérarchie] {e}" for e in processor.stats["errors"]])
        report.counts["régions"] = created
        if duplicates:
            report.warnings.append(f"[Hiérarchie] {duplicates} ligne(s) en double ignorée(s)")

        committee_levels = {}
        for name, c in conf["committees"].items():
            department = IssueDepartment.objects.create(name=name, processing_days=c["days"])
            committee_levels[name] = IssueDepartmentAdministrativeLevel.objects.create(
                department=department, administrative_level=level_objects[c["level"]]
            )
        report.counts["comités"] = len(committee_levels)

        # Appeal department (appeals are not used yet): the committee at the top level
        top = min(committee_levels.values(), key=lambda dl: conf["levels"].index(dl.administrative_level.name))
        types, subtypes = {}, {}
        for index, c in enumerate(conf["categories"], start=1):
            issue_type = types.get(c["type"]) or types.setdefault(c["type"], IssueType.objects.create(name=c["type"]))
            key = (c["type"], c["subtype"])
            subtype = subtypes.get(key) or subtypes.setdefault(
                key, IssueSubType.objects.create(name=c["subtype"], parent=issue_type)
            )
            assigned = committee_levels[c["committee"]]
            IssueCategory.objects.create(
                name=c["category"],
                abbreviation=c.get("abbreviation") or _abbreviation(index, c["category"]),
                parent=subtype,
                assigned_department=assigned,
                assigned_appeal_department=top,
                assigned_escalation_department=assigned,
                confidentiality_level=ANONYMOUS_CHOICE if c["sensitive"] else LOW_CHOICE,
                redirection_protocol=FEWER_ISSUES_CHOICE,
                processing_days=c["days"],
            )
        report.counts["types"] = len(types)
        report.counts["sous-types"] = len(subtypes)
        report.counts["catégories"] = len(conf["categories"])

        for flag, s in conf["statuses"].items():
            status = IssueStatus.objects.filter(**{flag: True}).first() or IssueStatus(**{flag: True})
            status.name = s["name"]
            status.threshold_days = s["days"]
            status.save()

        for name in conf["age_groups"]:
            CitizenAgeGroup.objects.create(name=name)
        report.counts["tranches d'âge"] = len(conf["age_groups"])
        for name, group_type in conf["citizen_groups"]:
            CitizenGroup.objects.create(
                name=name, type=CITIZEN_GROUP_CHOICE if group_type == "1" else CITIZEN_GROUP2_CHOICE
            )
        for name, comp in conf["components"].items():
            component = Component.objects.create(name=name, description=comp["description"])
            for sub_name, sub_description in comp["subs"]:
                SubComponent.objects.create(name=sub_name, description=sub_description, parent=component)
        report.counts["composantes"] = len(conf["components"])
        for name in conf["subprojects"]:
            SubProjectGroup.objects.create(name=name)
        report.counts["sous-projets"] = len(conf["subprojects"])

        # Every section filled: the GRM owner only reviews the summary and validates
        WizardSection.objects.exclude(name=SUMMARY_CHOICE).update(status=COMPLETED_CHOICE)
        WizardSection.objects.filter(name=SUMMARY_CHOICE).update(status=IN_PROGRESS_CHOICE)

    return report
