# Excel Imports — Configuration and Accounts

Two imports replace the long manual data entry of a new deployment:

1. **Configuration** — fills every step of the setup wizard from one workbook (levels, hierarchy, committees with their processing time, types / subtypes / categories with routing, statuses, age groups, components).
2. **Accounts** — creates the mobile accounts: committees (CCGP, CLGP, national committee) and field staff (FC, SC) with their covered villages.

Headers are matched without case or accents; extra columns are ignored (you can keep notes). Each workbook is **fully checked first: if anything is wrong, nothing is written** and every error is listed with its sheet and row.

---

## 1. Configuration import

**Where:**
- in the setup wizard, card **"Import from Excel"** (GRM owner, wizard not finished). You land on the summary: review it and click *Save and Finish*;
- or on the server: `python manage.py import_configuration configuration.xlsx`.

**When:** on a **fresh installation** only. The import replaces the configuration, so it is refused once issues or committee / field staff accounts exist.

| Sheet | Columns | Notes |
|---|---|---|
| **Projet** | Nom, Description | |
| **Niveaux** | Niveau | Top-down order, e.g. Pays, Département, Commune, Arrondissement, Village/Quartier |
| **Hiérarchie** | one column per level, **exactly** the level names in order | One row per full path; single root; extra spaces are cleaned |
| **Comités** | Comité, Niveau, Délai (jours ouvrables) | One committee per level that has one (e.g. CCGP / Village/Quartier / 3, CLGP / Commune / 3, Comité national / Pays / 5) |
| **Catégories** | Type, Sous-type, Catégorie, Comité, Délai spécifique (jours ouvrables), Confidentialité, Abréviation | *Type* = "Quel signalez-vous ?", *Sous-type* = "Quel type ?", *Catégorie* = "De quoi s'agit-il ?". *Comité* = who receives it (village committee → the committee where the issue happened). *Confidentialité*: `Sensible` = anonymous/sensitive. Category names must be unique. Abbreviation optional (generated) |
| Statuts *(optional)* | Statut (initial / ouvert / rejeté / résolu), Nom, Seuil (jours) | Default names and thresholds otherwise |
| **Tranches d'âge** | Tranche d'âge | |
| Groupes de citoyens *(optional)* | Nom, Type (1 or 2) | Leave out when not asked (Benin) |
| **Composantes** | Composante, Description, Sous-composante, Description sous-composante | Subcomponents are optional: one row per component, or one row per subcomponent |
| Sous-projets *(optional)* | Groupe de sous-projets | |

Appeals are not used yet: every category gets the top-level committee as appeal department.

---

## 2. Accounts import

**Where:**
- dashboard, **User Management → "Import accounts from Excel"** (GRM managers);
- or on the server: `python manage.py import_accounts comptes.xlsx`.

**Password:** every created account receives the **same initial password**, typed in the form or at the command prompt (asked twice) — it is never written in the file. Rule of the mobile login: at least 8 characters with letters and digits. (Changing one's password from the app is planned.)

**Run it after the configuration import:** committees and regions must exist. The login identifier is the **email**; accounts whose email already exists are skipped and listed.

| Sheet | Columns | Notes |
|---|---|---|
| **Comités** | Comité, Région (chemin), Prénom, Nom, Email | *Comité* = name from the configuration (CCGP, CLGP, Comité national). One account per committee |
| **Facilitateurs** | Rôle (FC / SC), Nom, Prénom(s), Email, Téléphone, Région de rattachement (chemin) | Reporter accounts: they report and follow issues, never process them |
| **Villages couverts** | Email, Chemin du village | One row per field staff account and village; these villages are offered by the app when reporting |

A *path* lists the region names from the root, separated by `>`: `Bénin > ALIBORI > BANIKOARA > FOUNOUGO > FOUNOUGO-YOMON`.

---

## 3. COSO Benin files

The COSO Benin workbooks are kept **outside the repositories** (they contain personal data) in `eMGP/config-coso/`:

- `import_configuration_coso.xlsx` — 5 levels, 952 regions, 3 committees (3 / 3 / 5 working days), 5 types, 24 categories (sensitive cases to the national committee, GBV 22 working days ≈ 30 calendar days), 5 age groups, 5 components without subcomponents, 9 subproject groups;
- `import_comptes_coso.xlsx` — 876 committee accounts (848 CCGP, 27 CLGP, national committee) and 110 field staff (83 FC, 27 SC) with 1,714 covered villages. Emails are placeholders `@mgp.bj` (`ccgp.<village>`, `clgp.<commune>`, `cnational`, `fc|sc.<prénom>.<nom>`).

Order on a new server: `migrate` → `import_configuration` → review and finish the wizard summary → `import_accounts`.
