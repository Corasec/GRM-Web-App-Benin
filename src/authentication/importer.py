"""
Import the mobile accounts from one Excel workbook (see docs/excel-import.md):
committee accounts (CCGP, CLGP, national committee) and field staff (FC, SC) with their villages.

Sheets (headers matched case- and accent-insensitively; extra columns ignored):

- "Comités":           Comité | Région (chemin) | Prénom | Nom | Email | Téléphone (opt.)
- "Facilitateurs":     Rôle (FC / SC) | Nom | Prénom(s) | Email | Téléphone | Région de rattachement (chemin)
- "Villages couverts": Email | Chemin du village

A path lists the region names from the root, separated by ">" (e.g. "Bénin > Alibori > Banikoara").
Every account gets the same initial password, given when importing (prompt / form) and never stored
in the file. The login identifier is the email. Existing emails are skipped. The workbook is fully
validated first: on any error nothing is written.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from django.contrib.auth.hashers import make_password
from django.db import transaction
from openpyxl import load_workbook

from authentication.models import Facilitator, GovernmentWorker, User
from issues.models import AdministrativeRegion, IssueDepartment

# Minimum strength of the shared initial password: at least 8 characters with letters and digits
PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,}$")
FIELD_ROLES = {"FC": Facilitator.ROLE_COMMUNITY_FACILITATOR, "SC": Facilitator.ROLE_COMMUNAL_SUPERVISOR}


class AccountsImportError(Exception):
    def __init__(self, errors):
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass
class AccountsImportReport:
    counts: dict = field(default_factory=dict)
    skipped: list = field(default_factory=list)


def norm(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def clean(value):
    return re.sub(r"\s+", " ", str(value)).strip() if value is not None else ""


def validate_password(password):
    if not password or not PASSWORD_PATTERN.match(password):
        raise AccountsImportError(
            [
                "Le mot de passe initial doit faire au moins 8 caractères et contenir des lettres et des chiffres "
                "(règle commune des mots de passe de l'application)."
            ]
        )


def _region_index():
    """Normalised full path ("benin > alibori > ...") -> region."""
    regions = {r.id: r for r in AdministrativeRegion.objects.all()}
    paths = {}

    def path(region):
        parts = []
        while region is not None:
            parts.append(norm(region.name))
            region = regions.get(region.parent_id)
        return " > ".join(reversed(parts))

    for region in regions.values():
        paths[path(region)] = region
    return paths


def _path_key(value):
    return " > ".join(norm(part) for part in str(value or "").split(">") if part.strip())


def _sheet_rows(wb, names, columns):
    wanted = {norm(n) for n in names}
    ws = next((w for w in wb.worksheets if norm(w.title) in wanted), None)
    if ws is None:
        return None, None
    header = [norm(c) for c in next(ws.iter_rows(min_row=1, max_row=1, values_only=True), [])]
    index = {}
    for key, aliases in columns.items():
        for alias in aliases:
            if norm(alias) in header:
                index[key] = header.index(norm(alias))
                break
    rows = []
    for number, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if any(c not in (None, "") for c in row):
            rows.append((number, {k: clean(row[i]) if i < len(row) else "" for k, i in index.items()}))
    return ws.title, (index, rows)


def read_accounts(file_obj):
    errors = []
    try:
        wb = load_workbook(file_obj, data_only=True, read_only=True)
    except Exception:
        raise AccountsImportError(["Le fichier n'est pas un classeur Excel (.xlsx) lisible."])

    regions = _region_index()
    departments = {norm(d.name): d for d in IssueDepartment.objects.all()}
    emails = set()

    def check_email(sheet, row, email):
        if not email or "@" not in email:
            errors.append(f"[{sheet}] ligne {row} : email invalide « {email} »")
            return False
        if email.lower() in emails:
            errors.append(f"[{sheet}] ligne {row} : email en double dans le fichier « {email} »")
            return False
        emails.add(email.lower())
        return True

    committees, field_staff, villages = [], {}, {}

    title, data = _sheet_rows(
        wb,
        ["Comités", "Comites", "Committees"],
        {
            "committee": ["Comité", "Comite", "Committee"],
            "path": ["Région (chemin)", "Chemin", "Region", "Path"],
            "first_name": ["Prénom", "Prenom", "Prénom (champ nom)", "First name"],
            "last_name": ["Nom", "Nom (champ nom)", "Last name"],
            "email": ["Email", "Email (identifiant)"],
            "phone": ["Téléphone", "Telephone", "Phone"],
        },
    )
    if data:
        index, rows = data
        missing = [k for k in ("committee", "path", "last_name", "email") if k not in index]
        if missing:
            errors.append(f"[{title}] colonne(s) manquante(s) : {', '.join(missing)}")
        else:
            seen = set()
            for row, r in rows:
                department = departments.get(norm(r["committee"]))
                region = regions.get(_path_key(r["path"]))
                if department is None:
                    errors.append(
                        f"[{title}] ligne {row} : comité inconnu « {r['committee']} » (voir la configuration)"
                    )
                if region is None:
                    errors.append(f"[{title}] ligne {row} : région introuvable « {r['path']} »")
                if department and region:
                    if (department.id, region.id) in seen:
                        errors.append(
                            f"[{title}] ligne {row} : un seul compte par comité ({r['committee']} — {region.name})"
                        )
                    seen.add((department.id, region.id))
                if check_email(title, row, r["email"]) and department and region:
                    committees.append({**r, "department": department, "region": region})

    title, data = _sheet_rows(
        wb,
        ["Facilitateurs", "Facilitators", "Personnel de terrain"],
        {
            "role": ["Rôle", "Role"],
            "last_name": ["Nom", "Last name"],
            "first_name": ["Prénom(s)", "Prénoms", "Prénom", "First name"],
            "email": ["Email", "Email (identifiant)"],
            "phone": ["Téléphone", "Telephone", "Phone"],
            "path": ["Région de rattachement (chemin)", "Chemin", "Région de rattachement", "Region"],
        },
    )
    if data:
        index, rows = data
        missing = [k for k in ("role", "last_name", "email", "path") if k not in index]
        if missing:
            errors.append(f"[{title}] colonne(s) manquante(s) : {', '.join(missing)}")
        else:
            for row, r in rows:
                match = re.search(r"\b(FC|SC)\b", r["role"].upper())
                role = FIELD_ROLES.get(match.group(1)) if match else None
                region = regions.get(_path_key(r["path"]))
                if role is None:
                    errors.append(f"[{title}] ligne {row} : rôle inconnu « {r['role']} » (FC ou SC)")
                if region is None:
                    errors.append(f"[{title}] ligne {row} : région de rattachement introuvable « {r['path']} »")
                if check_email(title, row, r["email"]) and role and region:
                    field_staff[r["email"].lower()] = {**r, "role": role, "region": region}

    title, data = _sheet_rows(
        wb,
        ["Villages couverts", "Covered villages"],
        {"email": ["Email", "Email (identifiant)"], "path": ["Chemin du village", "Chemin", "Village"]},
    )
    if data:
        index, rows = data
        if "email" not in index or "path" not in index:
            # Accept the explicit layout of the generated file: Pays | Département | ... | Village/Quartier
            errors.append(f"[{title}] colonnes « Email » et « Chemin du village » requises")
        else:
            for row, r in rows:
                village = regions.get(_path_key(r["path"]))
                if r["email"].lower() not in field_staff:
                    errors.append(f"[{title}] ligne {row} : email inconnu dans l'onglet Facilitateurs « {r['email']} »")
                elif village is None:
                    errors.append(f"[{title}] ligne {row} : village introuvable « {r['path']} »")
                elif village.children.exists():
                    errors.append(f"[{title}] ligne {row} : « {r['path']} » n'est pas un village")
                else:
                    villages.setdefault(r["email"].lower(), []).append(village)

    if not committees and not field_staff and not errors:
        errors.append("Aucun compte trouvé : onglets « Comités » et/ou « Facilitateurs » attendus.")
    if errors:
        raise AccountsImportError(errors)
    return committees, list(field_staff.values()), villages


def import_accounts(file_obj, password):
    """Validate then create the accounts with ``password`` as initial password."""
    validate_password(password)
    committees, field_staff, villages = read_accounts(file_obj)
    report = AccountsImportReport()
    # Same initial password for everybody: hash it once (hashing ~1000 accounts one by one takes minutes)
    encoded_password = make_password(password)
    existing = {e.lower() for e in User.objects.values_list("email", flat=True)}
    existing |= {u.lower() for u in User.objects.values_list("username", flat=True)}

    def create_user(r):
        email = r["email"].lower()
        if email in existing:
            report.skipped.append(f"{r['email']} : compte déjà existant, ignoré")
            return None
        user = User(
            username=email,
            email=email,
            first_name=r.get("first_name", ""),
            last_name=r.get("last_name", ""),
            phone_number=r.get("phone", "") or "",
        )
        user.password = encoded_password
        user.save()
        existing.add(email)
        return user

    with transaction.atomic():
        created_committees = 0
        for r in committees:
            if GovernmentWorker.objects.filter(department=r["department"], administrative_region=r["region"]).exists():
                report.skipped.append(
                    f"{r['email']} : le comité {r['committee']} — {r['region'].name} a déjà un compte"
                )
                continue
            user = create_user(r)
            if user:
                GovernmentWorker.objects.create(
                    user=user, department=r["department"], administrative_region=r["region"]
                )
                created_committees += 1
        created_staff = 0
        for r in field_staff:
            user = create_user(r)
            if user:
                facilitator = Facilitator.objects.create(user=user, role=r["role"], administrative_region=r["region"])
                facilitator.villages.set(villages.get(r["email"].lower(), []))
                created_staff += 1
    report.counts = {"comptes comité": created_committees, "comptes facilitateur": created_staff}
    return report
